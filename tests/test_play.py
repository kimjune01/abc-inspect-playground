import numpy as np
import pytest
from starlette.testclient import TestClient

from abc_inspect.server import create_server
from abc_inspect.session import Session


def test_cartesian_jog_is_physical_retry_safe_and_bounded(tmp_path):
    with Session(tmp_path, seed=7, max_steps=100, task="count_into_opaque_box") as session:
        first = session.observe()
        assert "tool_pose" in first
        moved = session.jog("jog", 0, translation=[0.01, 0, 0], yaw=0, gripper=None)
        assert moved["physics_steps"] == 5
        assert (
            moved["tool_pose"]["left"]["position"][0]
            > first["tool_pose"]["left"]["position"][0] + 0.002
        )
        duplicate = session.jog("jog", 0, translation=[0.01, 0, 0], yaw=0, gripper=None)
        assert duplicate["physics_steps"] == 5
        with pytest.raises(ValueError, match="stale"):
            session.jog("stale", 0, translation=[0, 0.01, 0], yaw=0, gripper=None)
        with pytest.raises(ValueError, match="translation"):
            session.jog("large", 1, translation=[1, 0, 0], yaw=0, gripper=None)
        rotated = session.jog("yaw", 1, translation=[0, 0, 0], yaw=0.08, gripper=None)
        assert not np.allclose(
            rotated["tool_pose"]["left"]["rotation"], moved["tool_pose"]["left"]["rotation"]
        )
        closed = session.jog("close", 2, translation=[0, 0, 0], yaw=0, gripper=0.0)
        assert closed["joint_pos"][6] < 0.3
        assert session.observe()["physics_steps"] == 15
        previous = closed
        for axis in (1, 2):
            delta = [0.0, 0.0, 0.0]
            delta[axis] = -0.015
            next_state = session.jog(
                f"axis-{axis}",
                previous["sequence"],
                translation=delta,
            )
            assert (
                next_state["tool_pose"]["left"]["position"][axis]
                < previous["tool_pose"]["left"]["position"][axis] - 0.002
            )
            previous = next_state


def test_play_routes_share_mcp_and_reject_foreign_origins(tmp_path):
    server, sessions = create_server(tmp_path, port=8876)
    try:
        with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:8876") as client:
            assert client.get("/play").status_code == 200
            assert (
                client.post(
                    "/play/api", headers={"Origin": "https://evil.example"}, json={}
                ).status_code
                == 403
            )
            assert (
                client.post("/play/api", headers={"Host": "evil.example"}, json={}).status_code
                == 403
            )
            payload = {
                "tool": "start_trial",
                "arguments": {
                    "request_id": "browser",
                    "max_steps": 20,
                    "task": "count_into_opaque_box",
                },
            }
            first = client.post("/play/api", json=payload).json()
            assert "session_id" in first, first
            assert first["session_id"] in sessions
            assert first["images"]["top"].startswith("data:image/png;base64,")
            moved = client.post(
                "/play/api",
                json={
                    "tool": "jog_arm",
                    "arguments": {
                        "session_id": first["session_id"],
                        "request_id": "key-w",
                        "expected_sequence": 0,
                        "translation": [0.01, 0, 0],
                    },
                },
            ).json()
            assert moved["physics_steps"] == 5
            assert sessions[first["session_id"]].observe()["sequence"] == 1
    finally:
        for session in sessions.values():
            session.close()
