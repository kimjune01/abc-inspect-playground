"""Scripted, privileged-setup demonstration; not a vision-agent benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import mink
import mujoco
import numpy as np
from inspect_robots import eval as inspect_eval
from inspect_robots.policy import PolicyConfig, PolicyInfo
from inspect_robots.scene import Scene
from inspect_robots.scorer import Score
from inspect_robots.task import Task
from inspect_robots.types import Action, ActionChunk

from abc_inspect.adapter import AbcEmbodiment, AbcSuccessScorer


class DemoEmbodiment(AbcEmbodiment):
    """Privileged evaluator-side height tracking; observations stay unchanged."""

    def __init__(self):
        super().__init__(task="count_into_opaque_box")
        self.tracked_object: int | None = None
        self.heights: list[float] = []

    def step(self, action):
        result = super().step(action)
        if self.tracked_object is not None:
            self.heights.append(float(self.env.data.subtree_com[self.tracked_object, 2]))
        return result


class PickPlacePolicy:
    """Mink IK with known initial object geometry and proprioceptive feedback."""

    def __init__(self, arm: DemoEmbodiment):
        self.arm = arm
        self.info = PolicyInfo(name="scripted-mink-pick-place", action_space=arm.info.action_space)
        self.config = PolicyConfig(action_horizon=1)
        self.index = 0
        self.phases: list[tuple[str, np.ndarray, float, int]] = []
        self.records: list[dict[str, Any]] = []
        self.grip_command: float | None = None

    def reset(self, scene):
        self.index = 0
        self.phases = []
        self.records = []
        self.grip_command = None

    def setup(self):
        m, d = self.arm.env.model, self.arm.env.data
        mujoco.mj_forward(m, d)
        self.joints = [m.joint(f"left_joint{i}").qposadr[0] for i in range(1, 7)]
        self.configuration = mink.Configuration(m)
        self.template = d.qpos.copy()
        for side in ("left", "right"):
            self.template[m.joint(f"{side}_right_finger").qposadr[0]] = -self.template[
                m.joint(f"{side}_left_finger").qposadr[0]
            ]
        self.frame = mink.FrameTask(
            frame_name="left_grasp_site",
            frame_type="site",
            position_cost=10.0,
            orientation_cost=1.0,
            gain=0.5,
            lm_damping=1e-5,
        )
        self.limits = [mink.ConfigurationLimit(m)]
        object_ids = [
            i
            for i in range(m.nbody)
            if m.body(i).name.startswith("count_obj_")
            and m.geom_type[m.body_geomadr[i]] == mujoco.mjtGeom.mjGEOM_BOX
        ]
        self.object_id = min(
            object_ids, key=lambda i: np.linalg.norm(d.subtree_com[i, :2] - np.array([0.43, 0.18]))
        )
        self.arm.tracked_object = self.object_id
        self.object_start = d.subtree_com[self.object_id].copy()
        down = np.array([0.0, 0.0, -1.0])
        cube_axes = d.xmat[self.object_id].reshape(3, 3)
        candidates: list[tuple[Any, ...]] = []
        for axis in (cube_axes[:, 0], -cube_axes[:, 0], cube_axes[:, 1], -cube_axes[:, 1]):
            axis = axis.copy()
            axis[2] = 0
            axis /= np.linalg.norm(axis)
            matrix = np.column_stack([axis, np.cross(down, axis), down])
            quat = np.zeros(4)
            mujoco.mju_mat2Quat(quat, matrix.reshape(-1))
            rotation = mink.SO3(quat)
            grasp = self.object_start.copy() - 0.03 * axis
            grasp[2] = self.object_start[2]
            pre = grasp.copy()
            pre[2] = 0.96
            qpre, epre = self.solve_pose(pre, rotation, self.template)
            qgrasp, egrasp = self.solve_pose(grasp, rotation, qpre)
            penetration = self.path_penetration(qpre, qgrasp)
            candidates.append(
                (epre + egrasp + 10 * penetration, rotation, grasp, pre, qpre, qgrasp)
            )
        error, self.rotation, grasp, pre, qpre, qgrasp = min(candidates, key=lambda c: c[0])
        if error > 0.03:
            raise RuntimeError(f"No accurate grasp pose: {error}")
        bin_id = m.body("opaque_count_box").id
        self.bin_position = d.xpos[bin_id].copy()
        self.initial_height = float(self.object_start[2])
        lift = pre.copy()
        lift[0] = 0.53
        lift[2] = 1.04
        above_bin = self.bin_position.copy()
        above_bin[2] = 1.04
        release = above_bin.copy()
        release[2] = 1.03
        retreat = above_bin.copy()
        retreat[2] = 1.08
        self.phases = [
            ("approach", pre, 1.0, 80),
            ("descend", grasp, 1.0, 60),
            ("grasp", grasp, 0.0, 50),
            ("lift", lift, 0.0, 160),
            ("transfer", above_bin, 0.0, 160),
            ("lower", release, 0.0, 35),
            ("release", release, 1.0, 30),
            ("retreat", retreat, 1.0, 50),
            ("settle", retreat, 1.0, 30),
        ]
        rotations = [c[1] for c in candidates]
        for angle in (np.pi / 6, np.pi / 4, np.pi / 3):
            tilt = np.array(
                [[np.cos(angle), 0, -np.sin(angle)], [0, 1, 0], [np.sin(angle), 0, np.cos(angle)]]
            )
            rotations.extend(mink.SO3.from_matrix(tilt @ c[1].as_matrix()) for c in candidates)
        self.pose_targets = {}
        q = self.template.copy()
        for name, pos, grip, length in self.phases:
            options = [
                self.solve_pose(pos, rot, q)
                for rot in (
                    [self.rotation] if name in ("approach", "descend", "grasp") else rotations
                )
            ]
            q, error = min(options, key=lambda option: option[1])
            if error > 0.03:
                raise RuntimeError(f"Unreachable {name} pose: {error}")
            self.pose_targets[name] = q[self.joints].copy()

    def path_penetration(self, start, end):
        m = self.arm.env.model
        check = mujoco.MjData(m)
        total = 0.0
        for fraction in np.linspace(0, 1, 25):
            # This is a separate FK/collision-check data object, never the simulated world.
            check.qpos[:] = start + fraction * (end - start)
            mujoco.mj_forward(m, check)
            for contact in check.contact:
                names = [m.body(m.geom_bodyid[g]).name for g in (contact.geom1, contact.geom2)]
                if any(n.startswith("left_") for n in names):
                    total += max(0.0, -contact.dist)
        return total

    def solve_pose(self, position, rotation, seed):
        self.configuration.update(q=seed)
        self.frame.set_target(mink.SE3.from_rotation_and_translation(rotation, position))
        for _ in range(80):
            velocity = mink.solve_ik(
                self.configuration, [self.frame], 0.034, "daqp", damping=1e-5, limits=self.limits
            )
            self.configuration.integrate_inplace(velocity, 0.034)
        error = self.frame.compute_error(self.configuration)
        return self.configuration.q.copy(), float(
            np.linalg.norm(error[:3]) + 0.1 * np.linalg.norm(error[3:])
        )

    def act(self, observation):
        if not self.phases:
            self.setup()
        offset = self.index
        for name, position, grip, length in self.phases:
            if offset < length:
                break
            offset -= length
        else:
            return ActionChunk(
                [
                    Action(
                        observation.state["joint_pos"].copy(),
                        meta={"request_stop": True, "stop_reason": "demo_completed"},
                    )
                ]
            )
        current = observation.state["joint_pos"].copy()
        target = current.copy()
        speed = 0.025 if name in ("lift", "transfer", "lower") else 0.045
        delta = self.pose_targets[name] - current[:6]
        # One scalar preserves the planned joint-space path. Per-joint clipping
        # changes that path and can drive the wrist camera into the box.
        target[:6] += delta * min(1.0, speed / max(float(np.max(np.abs(delta))), 1e-9))
        if self.grip_command is None:
            self.grip_command = float(current[6])
        self.grip_command += float(np.clip(grip - self.grip_command, -0.2, 0.2))
        target[6] = self.grip_command
        target = np.clip(target, self.info.action_space.low, self.info.action_space.high)
        self.index += 1
        self.records.append({"phase": name, "target": target.tolist()})
        return ActionChunk([Action(target, meta={"phase": name})])

    def transcript(self):
        return {
            "controller": "Mink IK",
            "privileged_setup": True,
            "note": "Uses known initial object geometry, not visual inference",
            "commands": self.records,
        }


class PickPlaceScorer:
    """Independent demonstration score, separate from ABC's sampled counting goal."""

    name = "pick_place"

    def __init__(self, arm, policy):
        self.arm, self.policy = arm, policy

    def __call__(self, record, target):
        info = self.arm.env.evaluate_task().to_info(squeeze=True)
        name = self.arm.env.model.body(self.policy.object_id).name
        lifted = max(self.arm.heights) - self.policy.initial_height > 0.12
        released = self.arm.last_observation.state["joint_pos"][6] > 0.9
        return Score(
            bool(name in info["objects_in_box"] and lifted and released),
            explanation="Selected cube lifted, released, and inside the box",
        )


def run_demo(directory: Path, *, store_frames=True):
    directory.mkdir(parents=True, exist_ok=True)
    previous_logs = set(directory.glob("abc-*.json"))
    arm = DemoEmbodiment()
    policy = PickPlacePolicy(arm)
    try:
        task = Task(
            name="abc-scripted-pick-place",
            scenes=[
                Scene(
                    id="seed-7", instruction="Pick up one cube and place it in the box", init_seed=7
                )
            ],
            scorer=[AbcSuccessScorer(), PickPlaceScorer(arm, policy)],
            max_steps=950,
            metadata={"demo": True, "privileged_initial_object_poses": True},
        )
        logs = inspect_eval(
            task,
            policy,
            arm,
            seed=7,
            log_dir=str(directory),
            store_frames=store_frames,
            fail_on_error=True,
        )
        result = arm.env.evaluate_task().to_info(squeeze=True)
        assert arm.last_observation is not None
        report = {
            "log_path": str(next(iter(set(directory.glob("abc-*.json")) - previous_logs))),
            "lift_height": max(arm.heights) - policy.initial_height,
            "objects_in_box": len(result.get("objects_in_box", [])),
            "placed_objects": result["objects_in_box"],
            "native_task_instruction": arm.env.prompt,
            "final_gripper": float(arm.last_observation.state["joint_pos"][6]),
            "physics_steps": arm.steps,
            "eval_status": logs[0].status,
            "task_metrics": dict(logs[0].results.metrics),
        }
        (directory / "result.json").write_text(
            json.dumps(report, indent=2, default=lambda x: x.tolist())
        )
        return report
    finally:
        arm.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("outputs/pick-place/run"))
    args = parser.parse_args()
    print(json.dumps(run_demo(args.output), indent=2))


if __name__ == "__main__":
    main()
