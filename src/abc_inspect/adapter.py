"""ABC environment adapted to Inspect; only Inspect calls reset/step during trials."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import mujoco
import numpy as np
from inspect_robots.embodiment import (
    AUTO_RESET,
    PRIVILEGED_SUCCESS,
    RENDERABLE,
    RESETTABLE,
    SEEDABLE,
    EmbodimentInfo,
)
from inspect_robots.rollout import TrialRecord
from inspect_robots.scene import Scene, Target
from inspect_robots.scorer import Score
from inspect_robots.spaces import ActionSemantics, Box, CameraSpec, ObservationSpace
from inspect_robots.types import Action, Observation, StepResult

ROOT = Path(__file__).resolve().parents[2]
ABC_REV = "d0832d12651d1b260a652861a14648dc5f3660c7"
TASK = "put_plastic_bottles_in_bin"


def import_abc():
    path = ROOT / "vendor" / "abc"
    if not (path / "abc_sim").is_dir():
        raise RuntimeError("ABC checkout missing. Run bash scripts/bootstrap.sh")
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
    import abc_sim

    return abc_sim


class AbcEmbodiment:
    def __init__(self, width: int = 224, height: int = 168, task: str = TASK):
        self.env = import_abc().make_env(
            task=task,
            camera_backend="mujoco",
            camera_height=height,
            camera_width=width,
            terminate_on_success=False,
        )
        self.last_observation: Observation | None = None
        self.steps = 0
        self.instruction = (
            "Put the plastic bottles in the bin"
            if task == TASK
            else "Pick up objects and place them in the box"
        )
        # ABC's generic Gym Box is [-1,1], but its arm commands are joint radians.
        # Use the actual actuator ranges; grippers are normalized [0,1] in ABC.
        low = self.env.model.actuator_ctrlrange[self.env._ctrl_indices, 0].copy()
        high = self.env.model.actuator_ctrlrange[self.env._ctrl_indices, 1].copy()
        low[[6, 13]], high[[6, 13]] = 0.0, 1.0
        self.info = EmbodimentInfo(
            name="abc_bottles" if task == TASK else f"abc_{task}",
            action_space=Box(
                shape=(14,),
                low=low,
                high=high,
                semantics=ActionSemantics(
                    control_mode="joint_pos",
                    gripper="continuous",
                    dim_labels=tuple(
                        f"{arm}_{joint}"
                        for arm in ("left", "right")
                        for joint in ("j1", "j2", "j3", "j4", "j5", "j6", "gripper")
                    ),
                ),
            ),
            observation_space=ObservationSpace(
                cameras=tuple(
                    CameraSpec(name=c, height=height, width=width) for c in self.env.camera_names
                ),
                state_keys=frozenset({"joint_pos"}),
            ),
            control_hz=1.0 / (self.env._physics_dt * self.env._control_decimation),
            is_simulated=True,
            capabilities=frozenset(
                {SEEDABLE, RESETTABLE, AUTO_RESET, PRIVILEGED_SUCCESS, RENDERABLE}
            ),
            environment_id=f"abc_sim/mujoco-{mujoco.__version__}",
            environment_revision=ABC_REV,
            docs="14 absolute joint targets: left 6 radians + gripper, right 6 radians + gripper; 0 closed, 1 open. Paused between calls.",
        )

    def _convert(self, obs: dict[str, Any]) -> Observation:
        result = Observation(
            images={
                k: np.ascontiguousarray(v.transpose(1, 2, 0)) for k, v in obs["images"].items()
            },
            state={"joint_pos": np.asarray(obs["state"], dtype=np.float64).copy()},
            instruction=self.instruction,
            image_times={k: float(v) for k, v in obs["camera_timestamps"].items()},
            state_time=float(self.env.data.time),
        )
        self.last_observation = result
        return result

    def reset(self, scene: Scene, *, seed: int | None = None) -> Observation:
        self.instruction = scene.instruction
        self.steps = 0
        self.env.forget_arm_state()
        obs, _ = self.env.reset(seed=seed, randomize=True)
        return self._convert(obs)

    def step(self, action: Action) -> StepResult:
        if action.meta.get("request_stop"):
            # Inspect's native stop protocol normally consumes an action; represent
            # this as a logged no-motion control event, without advancing physics.
            assert self.last_observation is not None
            evaluated = self.env.evaluate_task()
            metrics = evaluated.to_info(squeeze=True) if evaluated else {}
            return StepResult(
                self.last_observation, info={"abc": metrics, "control_event": "finish"}
            )
        target = np.asarray(action.data, dtype=np.float64)
        if target.shape != (14,) or not np.isfinite(target).all():
            raise ValueError("Expected 14 finite joint targets")
        low, high = self.info.action_space.low, self.info.action_space.high
        assert low is not None and high is not None
        if np.any(target < low) or np.any(target > high):
            raise ValueError("Joint target outside actuator limits")
        obs, reward, terminated, truncated, info = self.env.step(target)
        self.steps += 1
        return StepResult(
            self._convert(obs),
            reward=float(reward),
            terminated=terminated,
            truncated=truncated,
            info={"abc": info, "physics_step": self.steps},
        )

    def close(self) -> None:
        self.env.close()


class AbcSuccessScorer:
    """Uses ABC's recorded verdict, never the agent's claimed completion."""

    name = "abc_success"

    def __call__(self, record: TrialRecord, target: Target | None) -> Score:
        if not record.steps:
            return Score(None, explanation="No observation after an action")
        info = record.steps[-1].result.info.get("abc", {})
        value = info.get("task_success", info.get("success"))
        return Score(
            None if value is None else bool(value),
            explanation="ABC simulator oracle at final recorded state",
        )
