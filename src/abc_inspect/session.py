"""One Inspect-owned rollout per process, with serialized, retry-safe commands."""

from __future__ import annotations

import copy
import multiprocessing as mp
import os
import queue
import resource
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np

from abc_inspect.adapter import TASK, AbcEmbodiment, AbcSuccessScorer


def _run_trial(commands, responses, directory: str, seed: int, max_steps: int, task_name: str):
    # Keep the parent's MCP stdout a clean protocol channel.
    os.dup2(2, 1)
    from inspect_robots import eval as inspect_eval
    from inspect_robots.policy import PolicyConfig, PolicyInfo
    from inspect_robots.scene import Scene
    from inspect_robots.task import Task
    from inspect_robots.types import Action, ActionChunk

    arm = None
    started = time.monotonic()
    try:
        arm = AbcEmbodiment(task=task_name)
        from abc_inspect.teleop import Teleop

        teleop = Teleop(arm)
        embodiment_info = arm.info
        low, high = embodiment_info.action_space.low, embodiment_info.action_space.high
        assert low is not None and high is not None

        def packet(status="active", **extra):
            obs = arm.last_observation
            assert obs is not None
            return dict(
                status=status,
                images=dict(obs.images),
                joint_pos=obs.state["joint_pos"].tolist(),
                sim_time=obs.state_time,
                physics_steps=arm.steps,
                wall_elapsed_s=time.monotonic() - started,
                control_hz=arm.info.control_hz,
                instruction=obs.instruction,
                tool_pose=teleop.poses(),
                limits={
                    "low": low.tolist(),
                    "high": high.tolist(),
                },
                **extra,
            )

        class ExternalPolicy:
            info = PolicyInfo(name="external-mcp", action_space=embodiment_info.action_space)
            config = PolicyConfig(action_horizon=30)

            def __init__(self):
                self.calls = []

            def reset(self, scene):
                self.calls.clear()

            def act(self, observation):
                responses.put(packet())
                waiting = time.monotonic()
                try:
                    command = commands.get(timeout=900)
                except queue.Empty:
                    command = {
                        "kind": "finish",
                        "request_id": "idle-timeout",
                        "reason": "idle_timeout",
                    }
                self.calls.append({**command, "wait_wall_s": time.monotonic() - waiting})
                meta = {"request_id": command["request_id"]}
                if command["kind"] == "finish":
                    meta.update(request_stop=True, stop_reason=command["reason"])
                    return ActionChunk([Action(observation.state["joint_pos"].copy(), meta=meta)])
                if command["kind"] == "jog":
                    return teleop.actions(observation, command)
                teleop.grippers.clear()
                target = np.asarray(command["target"], dtype=np.float64)
                return ActionChunk(
                    [Action(target.copy(), meta=meta) for _ in range(command["steps"])]
                )

            def transcript(self):
                return {
                    "kind": "external_tool_commands",
                    "calls": self.calls,
                    "coverage": "Tool requests only; external agent context is not captured",
                }

        task = Task(
            name="abc-mcp-spike",
            scenes=[Scene(id=f"seed-{seed}", instruction=arm.instruction)],
            scorer=AbcSuccessScorer(),
            max_steps=max_steps,
            metadata={"clock": "paused_between_commands", "task": task_name, "prototype": True},
        )
        logs = inspect_eval(
            task, ExternalPolicy(), arm, log_dir=directory, store_frames=True, seed=seed
        )
        paths = list(Path(directory).glob("*.json"))
        responses.put(
            packet(
                status="finished",
                log_path=str(paths[0]),
                eval_status=logs[0].status,
                metrics=dict(logs[0].results.metrics),
                peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            )
        )
    except Exception as error:  # noqa: BLE001 - process boundary reports errors to the client
        import traceback

        responses.put({"error": str(error), "traceback": traceback.format_exc()})
    finally:
        if arm is not None:
            arm.close()


class Session:
    """Retry cache is process-local; a restart starts a new session, never a replay."""

    def __init__(
        self,
        log_root: Path,
        *,
        seed: int = 0,
        max_steps: int = 300,
        timeout: float = 60,
        task: str = TASK,
    ):
        if task not in (TASK, "count_into_opaque_box"):
            raise ValueError("Unsupported task")
        if not 1 <= max_steps <= 1000:
            raise ValueError("max_steps must be between 1 and 1000")
        self.id = uuid.uuid4().hex
        self.directory = (log_root / self.id).resolve()
        self.directory.mkdir(parents=True)
        self.max_steps = max_steps
        self.timeout = timeout
        self.lock = threading.RLock()
        self.cache: dict[str, tuple[dict, dict]] = {}
        self.pending: dict | None = None
        self.received: dict | None = None
        self.resources_released = False
        self.closed = False
        self.sequence = 0
        context = mp.get_context("spawn")
        self.commands = context.Queue()
        self.responses = context.Queue()
        self.process = context.Process(
            target=_run_trial,
            args=(self.commands, self.responses, str(self.directory), seed, max_steps, task),
            daemon=True,
        )
        self.process.start()
        try:
            self.current = self._receive()
        except BaseException:
            self._release_worker()
            raise

    def _receive(self):
        try:
            result = self.responses.get(timeout=self.timeout)
        except queue.Empty as error:
            raise TimeoutError(
                "Simulation response pending; retry the SAME request_id and payload"
            ) from error
        if "error" in result:
            self._release_worker()
            raise RuntimeError(result["traceback"])
        return {**result, "session_id": self.id, "sequence": self.sequence}

    def observe(self):
        with self.lock:
            if self.pending is not None:
                raise ValueError("Action pending; retry its request_id before observing")
            return self._restore(self.current)

    def _execute(self, command: dict[str, Any]):
        request_id = command["request_id"]
        if not request_id or len(request_id) > 128:
            raise ValueError("request_id must contain 1 to 128 characters")
        if request_id in self.cache:
            previous, result = self.cache[request_id]
            if previous != command:
                raise ValueError("request_id reused with a different payload")
            return self._restore(result)
        if self.pending is not None and self.pending != command:
            raise ValueError("Another action is pending; retry its original request_id and payload")
        if self.pending is None:
            if self.closed or self.current["status"] == "finished":
                raise ValueError("Session finished")
            if command["expected_sequence"] != self.sequence:
                raise ValueError(
                    "stale observation: expected_sequence does not match current sequence"
                )
            self._validate(command)
            self.commands.put(command)
            self.pending = command
        if self.received is None:
            self.received = self._receive()
        result = self.received
        result["sequence"] = self.sequence + 1
        # Persist before acknowledging. A failed write retains this single response
        # so an identical retry never requeues an action or waits for another result.
        archived = self._archive(result)
        self.sequence = result["sequence"]
        self.cache[request_id] = (copy.deepcopy(command), archived)
        self.current = archived if result["status"] == "finished" else result
        self.pending = None
        self.received = None
        if result["status"] == "finished":
            self._release_worker()
        return copy.deepcopy(result)

    def _archive(self, result: dict) -> dict:
        directory = self.directory / "retry-frames"
        directory.mkdir(exist_ok=True)
        destination = directory / f"{result['sequence']:04d}.npz"
        temporary = destination.with_suffix(".tmp")
        try:
            with temporary.open("wb") as stream:
                np.savez_compressed(stream, **result["images"])
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        metadata = copy.deepcopy({key: value for key, value in result.items() if key != "images"})
        metadata["_frames_path"] = str(destination)
        return metadata

    @staticmethod
    def _restore(result: dict) -> dict:
        restored = copy.deepcopy(result)
        path = restored.pop("_frames_path", None)
        if path is not None:
            with np.load(path, allow_pickle=False) as frames:
                restored["images"] = {name: frames[name] for name in frames.files}
        return restored

    def _release_worker(self):
        """Release OS resources once; archived observations and retries remain usable."""
        self.closed = True
        if self.resources_released:
            return
        self.process.join(timeout=5)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=5)
        for channel in (self.commands, self.responses):
            channel.close()
            channel.join_thread()
        self.process.close()
        self.resources_released = True

    def _validate(self, command):
        if command["kind"] == "finish":
            if len(command["reason"]) > 200:
                raise ValueError("reason must be at most 200 characters")
            return
        if not 1 <= command["steps"] <= 30:
            raise ValueError("steps must be between 1 and 30")
        remaining = self.max_steps - self.current["physics_steps"]
        if command["steps"] > remaining:
            raise ValueError(f"Only {remaining} physics steps remain")
        if command["kind"] == "jog":
            translation = np.asarray(command["translation"], dtype=float)
            if (
                translation.shape != (3,)
                or not np.isfinite(translation).all()
                or np.linalg.norm(translation) > 0.026
            ):
                raise ValueError(
                    "translation must be 3 finite values totaling at most 0.026 metres"
                )
            if not np.isfinite(command["yaw"]) or abs(command["yaw"]) > 0.12:
                raise ValueError("yaw must be at most 0.12 radians")
            if command["arm"] not in ("left", "right"):
                raise ValueError("arm must be left or right")
            if command["gripper"] is not None and command["gripper"] not in (0.0, 1.0):
                raise ValueError("gripper must be 0, 1 or null")
            return
        target = np.asarray(command["target"], dtype=float)
        if target.shape != (14,) or not np.isfinite(target).all():
            raise ValueError("Expected 14 finite joint targets")
        bounds = self.current["limits"]
        if np.any(target < bounds["low"]) or np.any(target > bounds["high"]):
            raise ValueError("Joint target outside actuator limits")
        delta = np.abs(target - self.current["joint_pos"])
        max_delta = np.full(14, 0.2)
        max_delta[[6, 13]] = 0.25
        if np.any(delta > max_delta):
            raise ValueError("Per-command change exceeds 0.2 radians or 0.25 gripper range")

    def move(self, request_id: str, expected_sequence: int, target: list[float], *, steps: int = 5):
        with self.lock:
            return self._execute(
                {
                    "kind": "move",
                    "request_id": request_id,
                    "expected_sequence": expected_sequence,
                    "target": list(target),
                    "steps": steps,
                }
            )

    def jog(
        self,
        request_id: str,
        expected_sequence: int,
        *,
        translation: list[float],
        yaw: float = 0.0,
        gripper: float | None = None,
        arm: str = "left",
        steps: int = 5,
    ):
        with self.lock:
            return self._execute(
                {
                    "kind": "jog",
                    "request_id": request_id,
                    "expected_sequence": expected_sequence,
                    "translation": list(translation),
                    "yaw": yaw,
                    "gripper": gripper,
                    "arm": arm,
                    "steps": steps,
                }
            )

    def finish(self, request_id: str, expected_sequence: int, *, reason: str = "agent_finished"):
        with self.lock:
            return self._execute(
                {
                    "kind": "finish",
                    "request_id": request_id,
                    "expected_sequence": expected_sequence,
                    "reason": reason,
                }
            )

    def close(self):
        with self.lock:
            try:
                if self.pending is not None and not self.closed:
                    self._execute(self.pending)
                if not self.closed and self.current["status"] != "finished":
                    self.finish("session-close", self.sequence, reason="session_closed")
            finally:
                self._release_worker()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
