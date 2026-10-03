import json
from pathlib import Path

import pytest
from inspect_robots.scene import Scene
from inspect_robots.types import Action
from starlette.testclient import TestClient

from abc_inspect.adapter import AbcEmbodiment, import_abc
from abc_inspect.server import create_server

TASKS = [
    ("count_one_into_opaque_box", 1),
    ("count_two_into_opaque_box", 2),
    ("count_three_into_opaque_box", 3),
    ("spell_cat", "CAT"),
    ("spell_dog", "DOG"),
    ("spell_fish", "FISH"),
]


@pytest.mark.parametrize("name, goal", TASKS)
def test_catalog_goals_match_upstream_evaluators(name, goal):
    spec = import_abc().get_task_spec(name)
    arm = AbcEmbodiment(task=name)
    try:
        observation = arm.reset(Scene(id="catalog", instruction=spec.prompt), seed=7)
        assert observation.instruction == spec.prompt
        assert set(observation.state) == {"joint_pos"}
        info = arm.step(Action(observation.state["joint_pos"])).info["abc"]["task_eval"]
        if isinstance(goal, int):
            assert info["target_count"] == goal
            metadata = arm.env._last_randomization.metadata
            assert set(metadata["eligible_objects"]) == {obj["name"] for obj in metadata["objects"]}
            # Test the original scorer against an isolated configuration array,
            # without changing the simulated world.
            evaluator = arm.env._task_evaluator
            qpos = arm.env.data.qpos.copy()
            for index, obj in enumerate(metadata["objects"][: goal + 1]):
                adr = arm.env.model.joint(obj["joint"]).qposadr[0]
                qpos[adr : adr + 3] = [0.70, 0, 0.80]
                assert evaluator.evaluate_qpos_batch(qpos[None]).scalar_success() == (
                    index + 1 == goal
                )
        else:
            assert info["word"] == goal
    finally:
        arm.close()


def test_scene_catalog_and_switching_keep_task_goal_score_and_attribution_together(tmp_path):
    server, sessions = create_server(tmp_path, port=8876)
    try:
        with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:8876") as client:
            response = client.get("/play/catalog")
            assert response.status_code == 200
            catalog = response.json()
            assert len(catalog["scenes"]) == 2
            assert all(len(scene["tasks"]) == 3 for scene in catalog["scenes"])
            assert {t["id"] for scene in catalog["scenes"] for t in scene["tasks"]} == {
                n for n, _ in TASKS
            }
            assert client.get("/play/catalog", headers={"Host": "evil.example"}).status_code == 403
            for scene in catalog["scenes"]:
                for task in scene["tasks"]:
                    assert "github.com/amazon-far/abc/blob/" in task["source_url"]
                    assert "task_eval/" in task["evaluator_url"]
                    assert task["max_steps"] == (5000 if scene["id"] == "letter_blocks" else 1000)
                    started = client.post(
                        "/play/api",
                        json={
                            "tool": "start_trial",
                            "arguments": {
                                "request_id": task["id"],
                                "task": task["id"],
                                "seed": 7,
                                "max_steps": 3,
                            },
                        },
                    ).json()
                    assert "error" not in started, started
                    assert started["task_id"] == task["id"]
                    assert started["scene_id"] == scene["id"]
                    assert started["instruction"] == import_abc().get_task_spec(task["id"]).prompt
                    assert started["benchmark"]["state"] == "pending"
                    final = client.post(
                        "/play/api",
                        json={
                            "tool": "finish_trial",
                            "arguments": {
                                "session_id": started["session_id"],
                                "request_id": "end-" + task["id"],
                                "expected_sequence": 0,
                            },
                        },
                    ).json()
                    assert final["task_id"] == task["id"]
                    log = json.loads(Path(final["log_path"]).read_text())
                    assert log["results"]["metrics"]["abc_success"] == final["benchmark"]["score"]
            # Navigation must keep working after more than eight attempts, while
            # old start IDs must never silently create a second trial.
            for index in range(3):
                started = client.post(
                    "/play/api",
                    json={
                        "tool": "start_trial",
                        "arguments": {
                            "request_id": f"extra-{index}",
                            "task": "count_one_into_opaque_box",
                            "max_steps": 3,
                        },
                    },
                ).json()
                assert "error" not in started, started
                client.post(
                    "/play/api",
                    json={
                        "tool": "finish_trial",
                        "arguments": {
                            "session_id": started["session_id"],
                            "request_id": f"end-extra-{index}",
                            "expected_sequence": 0,
                        },
                    },
                )
            assert len(sessions) == 8
            old = client.post(
                "/play/api",
                json={
                    "tool": "start_trial",
                    "arguments": {
                        "request_id": TASKS[0][0],
                        "task": TASKS[0][0],
                        "seed": 7,
                        "max_steps": 3,
                    },
                },
            ).json()
            assert "archived" in old["error"]
    finally:
        for session in sessions.values():
            session.close()
