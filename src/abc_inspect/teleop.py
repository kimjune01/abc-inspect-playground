"""Robot-only forward/inverse kinematics; no object pose or oracle access."""

import mink
import numpy as np


class Teleop:
    def __init__(self, arm):
        self.arm = arm
        self.configure()

    def configure(self):
        self.model = self.arm.env.model
        self.configuration = mink.Configuration(self.model)
        self.frames = {
            side: mink.FrameTask(
                frame_name=f"{side}_grasp_site",
                frame_type="site",
                position_cost=10.0,
                orientation_cost=1.0,
                gain=0.5,
                lm_damping=1e-5,
            )
            for side in ("left", "right")
        }
        self.limits = [mink.ConfigurationLimit(self.model)]
        self.grippers: dict[str, float] = {}

    def sync(self):
        # ABC can rebuild the model with a different object count during reset.
        if self.model is not self.arm.env.model:
            self.configure()
        self.configuration.update(q=self.arm.env.data.qpos)

    def poses(self):
        self.sync()
        return {
            side: {
                "position": pose.translation().tolist(),
                "rotation": pose.rotation().as_matrix().tolist(),
            }
            for side in self.frames
            for pose in [
                self.configuration.get_transform_frame_to_world(f"{side}_grasp_site", "site")
            ]
        }

    def actions(self, observation, command):
        from inspect_robots.types import Action, ActionChunk

        self.sync()
        side = command["arm"]
        offset = 0 if side == "left" else 7
        pose = self.configuration.get_transform_frame_to_world(f"{side}_grasp_site", "site")
        rotation = mink.SO3.exp(np.array([0.0, 0.0, command["yaw"]])) @ pose.rotation()
        self.frames[side].set_target(
            mink.SE3.from_rotation_and_translation(
                rotation,
                pose.translation() + np.asarray(command["translation"]),
            )
        )
        for _ in range(25):
            velocity = mink.solve_ik(
                self.configuration,
                [self.frames[side]],
                0.034,
                "daqp",
                damping=1e-5,
                limits=self.limits,
            )
            self.configuration.integrate_inplace(velocity, 0.034)
        observed = observation.state["joint_pos"].copy()
        indices = [self.model.joint(f"{side}_joint{i}").qposadr[0] for i in range(1, 7)]
        delta = self.configuration.q[indices] - observed[offset : offset + 6]
        # Preserve the coordinated IK direction while bounding the whole command.
        delta *= min(1.0, 0.18 / max(float(np.max(np.abs(delta))), 1e-9))
        if command["gripper"] is not None:
            self.grippers[side] = command["gripper"]
        grip_target = self.grippers.get(side)
        actions = []
        low, high = self.arm.info.action_space.low, self.arm.info.action_space.high
        for tick in range(command["steps"]):
            target = observed.copy()
            target[offset : offset + 6] += delta * (tick + 1) / command["steps"]
            if grip_target is not None:
                target[offset + 6] += np.clip(
                    grip_target - observed[offset + 6], -0.2 * (tick + 1), 0.2 * (tick + 1)
                )
            target = np.clip(target, low, high)
            actions.append(
                Action(
                    target, meta={"request_id": command["request_id"], "control": "cartesian_jog"}
                )
            )
        return ActionChunk(actions)
