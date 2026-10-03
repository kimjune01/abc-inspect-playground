"""Real process isolation and retry semantics, driven through Inspect's loop."""

import json
from pathlib import Path

import numpy as np
import pytest

from abc_inspect.session import Session


def test_idempotent_actions_stale_reads_and_inspect_finish(tmp_path):
    with Session(tmp_path, seed=7, max_steps=40) as session:
        first = session.observe()
        assert first["sequence"] == 0
        assert set(first["images"]) == {"top", "left", "right"}
        target = list(first["joint_pos"])
        target[0] += 0.05
        moved = session.move("move-1", 0, target, steps=5)
        assert moved["sequence"] == 1
        assert moved["physics_steps"] == 5
        assert moved["sim_time"] > first["sim_time"]
        duplicate = session.move("move-1", 0, target, steps=5)
        assert duplicate["sim_time"] == moved["sim_time"]
        assert session.observe()["physics_steps"] == 5
        with pytest.raises(ValueError, match="reused"):
            session.move("move-1", 0, target, steps=4)
        with pytest.raises(ValueError, match="stale"):
            session.move("move-2", 0, target, steps=5)
        with pytest.raises(ValueError, match="finite"):
            session.move("nan", 1, [float("nan")] * 14, steps=1)
        end = session.finish("finish-1", 1, reason="prototype_completed")
        assert end["status"] == "finished"
        assert session.resources_released
        assert end["physics_steps"] == 5
        assert end["sim_time"] == moved["sim_time"]
        log = json.loads(Path(end["log_path"]).read_text())
        assert log["status"] == "success"
        assert log["results"]["metrics"]["abc_success"] == 0.0
        assert "move-1" in json.dumps(log)
        assert "prototype_completed" in json.dumps(log)
        assert (
            session.finish("finish-1", 1, reason="prototype_completed")["log_path"]
            == end["log_path"]
        )
        with pytest.raises(ValueError, match="finished"):
            session.move("move-after-end", end["sequence"], target, steps=1)


def test_fresh_sessions_replay_same_initial_state_and_motion(tmp_path):
    observations = []
    for index in range(2):
        with Session(tmp_path / str(index), seed=17, max_steps=5) as session:
            obs = session.observe()
            target = list(obs["joint_pos"])
            target[0] += 0.03
            obs = session.move("nudge", 0, target, steps=3)
            observations.append(obs)
            session.finish("end", 1)
    np.testing.assert_allclose(
        observations[0]["joint_pos"], observations[1]["joint_pos"], atol=1e-8
    )
    assert observations[0]["sim_time"] == observations[1]["sim_time"]


def test_budget_finishes_trial_without_extra_policy_call(tmp_path):
    with Session(tmp_path, seed=7, max_steps=2) as session:
        first = session.observe()
        last = session.move("hold", 0, first["joint_pos"], steps=2)
        assert last["status"] == "finished"
        assert last["physics_steps"] == 2
        assert Path(last["log_path"]).exists()


def test_timeout_retry_and_concurrent_writers_do_not_double_step(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    with Session(tmp_path, seed=7, max_steps=30) as session:
        first = session.observe()
        real_receive = session._receive
        with monkeypatch.context() as patch:

            def simulate_transport_timeout():
                raise TimeoutError("simulated response timeout")

            patch.setattr(session, "_receive", simulate_transport_timeout)
            with pytest.raises(TimeoutError):
                session.move("slow", 0, first["joint_pos"], steps=2)
        assert session._receive == real_receive
        with pytest.raises(ValueError, match="pending"):
            session.move("different", 0, first["joint_pos"], steps=2)
        recovered = session.move("slow", 0, first["joint_pos"], steps=2)
        assert recovered["physics_steps"] == 2

        def writer(request):
            try:
                return session.move(request, 1, recovered["joint_pos"], steps=2)
            except ValueError as error:
                return str(error)

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(writer, ["agent-a", "agent-b"]))
        assert sum(isinstance(outcome, dict) for outcome in outcomes) == 1
        assert sum("stale" in outcome for outcome in outcomes if isinstance(outcome, str)) == 1
        assert session.observe()["physics_steps"] == 4


def test_rejected_large_command_does_not_advance_physics(tmp_path):
    with Session(tmp_path, seed=7, max_steps=3) as session:
        first = session.observe()
        target = list(first["joint_pos"])
        target[0] += 0.3
        with pytest.raises(ValueError, match="Per-command"):
            session.move("too-big", 0, target, steps=1)
        with pytest.raises(ValueError, match="remain"):
            session.move("too-long", 0, first["joint_pos"], steps=4)
        assert session.observe()["physics_steps"] == 0
        assert session.observe()["sequence"] == 0


def retained_array_bytes(value):
    if isinstance(value, np.ndarray):
        return value.nbytes
    if isinstance(value, dict):
        return sum(retained_array_bytes(item) for item in value.values())
    if isinstance(value, (tuple, list)):
        return sum(retained_array_bytes(item) for item in value)
    return 0


def test_finished_sessions_release_images_and_worker_but_keep_exact_retries(tmp_path):
    with Session(tmp_path, seed=7, max_steps=12) as session:
        first = session.observe()
        target = first["joint_pos"]
        original = session.move("first", 0, target, steps=1)
        expected_images = {name: pixels.copy() for name, pixels in original["images"].items()}
        # Callers must not be able to mutate the persisted retry response.
        original["images"]["top"][:] = 0
        for index in range(1, 12):
            current = session.observe()
            session.move(f"next-{index}", index, current["joint_pos"], steps=1)
        assert session.current["status"] == "finished"
        assert retained_array_bytes(session.cache) == 0
        assert retained_array_bytes(session.current) == 0
        assert session.resources_released
        with pytest.raises(ValueError, match="closed"):
            _ = session.process.sentinel
        retry = session.move("first", 0, target, steps=1)
        assert retry["sequence"] == 1
        assert retry["physics_steps"] == 1
        for name, pixels in retry["images"].items():
            np.testing.assert_array_equal(pixels, expected_images[name])
        assert session.observe()["physics_steps"] == 12
        session.close()
        session.close()
        assert session.move("first", 0, target, steps=1)["physics_steps"] == 1


def test_disk_cache_failure_retry_does_not_lose_or_repeat_motion(tmp_path, monkeypatch):
    with Session(tmp_path, seed=7, max_steps=10) as session:
        first = session.observe()
        with monkeypatch.context() as patch:

            def disk_full(*args, **kwargs):
                raise OSError("disk full")

            patch.setattr(np, "savez_compressed", disk_full)
            with pytest.raises(OSError, match="disk full"):
                session.move("recover", 0, first["joint_pos"], steps=2)
        with pytest.raises(ValueError, match="pending"):
            session.move("different", 0, first["joint_pos"], steps=2)
        recovered = session.move("recover", 0, first["joint_pos"], steps=2)
        assert recovered["physics_steps"] == 2
        assert recovered["sequence"] == 1
        assert retained_array_bytes(session.cache) == 0
        assert session.observe()["physics_steps"] == 2


def test_letter_tasks_allow_five_times_the_box_budget(tmp_path):
    for task, limit in [("spell_cat", 5000), ("count_one_into_opaque_box", 1000)]:
        with pytest.raises(ValueError, match="max_steps"):
            Session(tmp_path, task=task, max_steps=limit + 1)
    with Session(tmp_path, task="spell_cat", max_steps=5000) as session:
        first = session.observe()
        assert first["max_steps"] == 5000
        moved = session.move("budget-move", 0, first["joint_pos"], steps=2)
        assert moved["max_steps"] == 5000
        assert moved["status"] == "active"
        final = session.finish("budget-finish", 1)
        assert final["max_steps"] == 5000
