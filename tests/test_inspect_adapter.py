"""The same ABC environment must participate in Inspect's real eval loop."""

import json

import numpy as np
from inspect_robots import eval as inspect_eval
from inspect_robots import read_eval_log
from inspect_robots.policy import PolicyConfig, PolicyInfo
from inspect_robots.scene import Scene
from inspect_robots.task import Task
from inspect_robots.types import Action, ActionChunk

from abc_inspect.adapter import AbcEmbodiment, AbcSuccessScorer


def test_reset_restores_robot_pose_after_motion():
    arm = AbcEmbodiment()
    try:
        scene = Scene(id="bottles", instruction="Put the bottles in the bin")
        initial = arm.reset(scene, seed=7)
        target = initial.state["joint_pos"].copy()
        target[0] += 0.1
        for _ in range(5):
            arm.step(Action(target))
        again = arm.reset(scene, seed=7)
        np.testing.assert_allclose(again.state["joint_pos"], initial.state["joint_pos"], atol=1e-8)
        assert again.images["top"].shape == (168, 224, 3)
        assert set(again.state) == {"joint_pos"}, "Do not leak simulator object poses"
    finally:
        arm.close()


def test_inspect_writes_readable_scored_log_and_frames(tmp_path):
    arm = AbcEmbodiment()

    class NudgePolicy:
        info = PolicyInfo(name="scripted-nudge", action_space=arm.info.action_space)
        config = PolicyConfig(action_horizon=1)

        def reset(self, scene):
            pass

        def act(self, observation):
            target = observation.state["joint_pos"].copy()
            target[0] += 0.02
            return ActionChunk([Action(target)])

    try:
        task = Task(
            name="abc-bottles-spike",
            scenes=[Scene(id="seed-7", instruction="Put the bottles in the bin")],
            scorer=AbcSuccessScorer(),
            max_steps=3,
        )
        logs = inspect_eval(
            task, NudgePolicy(), arm, log_dir=str(tmp_path), store_frames=True, seed=7
        )
        assert logs[0].status == "success"  # Harness completion, not task success.
        assert logs[0].results.metrics["abc_success"] == 0.0
        files = list(tmp_path.glob("*.json"))
        assert files
        restored = read_eval_log(str(files[0]))
        assert restored.status == "success"
        serialized = json.loads(files[0].read_text())
        assert "abc_bottles" in json.dumps(serialized)
        frames = list(tmp_path.rglob("*.npy"))
        assert frames
        assert np.load(frames[0]).shape == (168, 224, 3)
    finally:
        arm.close()
