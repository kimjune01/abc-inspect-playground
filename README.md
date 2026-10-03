# ABC Inspect Playground

Play with a simulated robot in Chrome, or let a TUI agent drive it through MCP.
ABC Sim supplies the robot and physics; Inspect Robots runs and records each trial.
Everything runs locally, without robot hardware or policy-model weights.

**Working today:** keyboard control of either arm, live camera updates, stateful MCP
commands, native Inspect logs, and a scripted cube pick-and-place demonstration.
This is a prototype for developing robotics benchmarks, not a validated benchmark.

[Roadmap](ROADMAP.md) · [Initial integration measurements](DERISK.md)

## Start and play

Tested on an Apple M3 laptop with 16 GiB RAM and macOS. Other platforms have not
been verified. You need Git, `uv`, Chrome, and a working graphics context for
MuJoCo cameras. Setup downloads the pinned dependencies and selected ABC assets.

```sh
cd /Users/junekim/Documents/abc-inspect-prototype
bash scripts/bootstrap.sh  # first-time setup
bash scripts/serve.sh
```

Open **http://127.0.0.1:8876/play** in Chrome and click **Start**.
If the server is already running, use that page; the launch script checks the port.

| Control | Movement |
| --- | --- |
| W / S | Forward / back (world X) |
| A / D | Left / right (world Y) |
| ↑ / ↓ | Up / down (world Z) |
| ← / → | Rotate around the vertical axis (yaw) |
| Space | Close / open the selected gripper |
| Arm selector | Switch between left and right arms |
| Reset | Finish the current trial and start a fresh scene |
| Escape | Stop sending movement commands |

Hold a key to keep moving. The on-screen buttons also work. Releasing a key or
switching away stops further movement commands; an in-flight command completes.
Each browser command advances up to five physics ticks, about 0.17 simulated
seconds. Cameras update after each command, and physics pauses between commands.
This is interactive control, not a continuous real-time video stream.

The wrist keeps its existing tilt while yawing. There are no pitch/roll controls
yet, and reach limits or collisions may prevent movement. Keyboard play opens the
cube-and-box scene; the scripted demo below uses its own grasp controller.

A browser trial lasts at most 1,000 physics ticks. Reset to play again. The server
retains at most eight trials per run; restart it after reaching that limit. Server
restarts invalidate sessions: refresh the page and click Start again.

## Let a TUI agent drive

The shared MCP endpoint is **http://127.0.0.1:8876/mcp**. The browser and agents use
the same tools and the same active-trial registry. Coordinate who controls a
trial; there is no explicit human/agent ownership handoff yet.

`.codex/config.toml` contains a project-local `abc_sim` registration. A new trusted
Codex session must load that configuration. Direct discovery in a fresh TUI
session remains unverified; a subagent has successfully used the protocol helper:

```sh
uv run python -m abc_inspect.client start_trial \
  '{"request_id":"trial-1","seed":7,"max_steps":100,"task":"count_into_opaque_box"}'
```

The helper prints metadata and saves the three camera PNGs. Inspect those images
before choosing an action. Substitute the returned session ID and sequence:

```sh
uv run python -m abc_inspect.client jog_arm \
  '{"session_id":"SESSION_ID","request_id":"move-1","expected_sequence":0,"translation":[0.01,0,0],"yaw":0,"arm":"left"}'

uv run python -m abc_inspect.client finish_trial \
  '{"session_id":"SESSION_ID","request_id":"finish-1","expected_sequence":1,"reason":"done"}'
```

Arguments can also come from `@file.json`. Finish the browser's active trial or
stop/reset the server before starting a separate agent trial.

### Tool contract

| Tool | Purpose |
| --- | --- |
| `start_trial(request_id, seed=7, max_steps=300, task=…)` | Create the single active trial; return state and cameras |
| `observe(session_id)` | Read the latest completed state without stepping physics |
| `jog_arm(session_id, request_id, expected_sequence, translation, yaw=0, gripper=null, arm="left", steps=5)` | Move using robot-only inverse kinematics |
| `move_joints(session_id, request_id, expected_sequence, target, steps=5)` | Apply bounded absolute joint targets |
| `finish_trial(session_id, request_id, expected_sequence, reason=…)` | Finish without moving; return final metrics and log path |

Supported tasks are `put_plastic_bottles_in_bin` (the MCP default) and
`count_into_opaque_box` (the browser default).

- **Observations:** three RGB cameras, 14 joint values, robot grasp-site poses,
  actuator limits, sequence, status, and simulated time. Live observations exclude
  object poses and task scores.
- **Cartesian jog:** a three-value world-frame translation in metres, norm at most
  0.026; world-Z yaw at most ±0.12 radians. Gripper is `0` closed, `1` open, or `null`
  to retain its command. IK produces bounded actuator targets, not guaranteed motion.
- **Joint targets:** left six joint radians, left gripper, right six joint radians,
  right gripper. Maximum change from observed state is 0.2 radians per joint and
  0.25 per gripper. Use the returned actuator bounds.
- **Timing:** 1–30 ticks per tool action, at approximately 29.41 simulated Hz.
  Trials allow 1–1,000 ticks and have a 15-minute idle timeout.
- **Retries:** use a fresh request ID and latest sequence for a new action. After a
  timeout, retry the **same ID and identical arguments**. Duplicate requests do not
  move twice, but their cached observations can be old; observe before a new decision.
- **Concurrency:** commands serialize; stale sequences are rejected. HTTP reconnects
  preserve the robot trial. Restarting the server clears sessions and retry history.

## Inspect integration and records

```text
Chrome keyboard ─┐
                 ├─ shared tools → session queue → Inspect Policy → ABC Embodiment
TUI agent / MCP ─┘                                      │                 │
                                                  native logs       MuJoCo physics
```

`inspect_robots.eval` owns every reset and physics step. The external policy
supplies action chunks; the adapter converts ABC observations; the scorer reads
ABC's evaluator. Mink solves robot kinematics on a separate model. Neither user
commands nor agent commands teleport the simulated robot or objects.

Trials write native JSON, action metadata, an external-command transcript, and
`.npy` camera frames under `outputs/trials/SESSION/`. The transcript records tool
commands, not the agent's complete prompts or conversation.

**Harness completion is not task success.** `eval_status: success` means the
rollout completed; `abc_success` is ABC's independent task verdict. Finishing is a
logged no-motion event: Inspect counts it as a step, but `physics_steps` excludes it.
The browser's generic task instruction is not yet a precise benchmark specification
for ABC's sampled counting objective.

For a native Inspect report, substitute the returned `log_path`:

```sh
uv run inspect-robots view outputs/trials/SESSION/LOG.json --no-video -o outputs/report.html
```

Camera playback in that report has not been verified here. Use the replay helper
below to render the recorded frames into videos. Reports and replays do not control
the active simulator.

## Scripted pick-and-place demo

```sh
uv run python -m abc_inspect.pick_place --output outputs/pick-place/run
uv run python scripts/render_replay.py outputs/pick-place/run
```

The replay renderer needs `ffmpeg`. Open `outputs/demo/index.html`. Use a fresh
output directory for each run so the renderer receives one trial's frames.
The earlier page on port 8877, if still running, serves this recorded demo.

The controller uses **known initial object geometry** and Mink IK to physically
lift a cube and release it into the box. This is a privileged scripted baseline;
it does not demonstrate visual reasoning or agent-driven pick-and-place over MCP.

`pick_place=1` requires the selected cube to rise more than 12 cm, end inside the
box, and have the gripper open. `abc_success` may remain zero because ABC's sampled
counting objective asks for more objects. The integration test verifies one fixed
seed. Bottle pick-and-place remains unreliable.

## Development

```sh
uv run pytest -q
uv run ruff check src tests
uv run mypy src/abc_inspect
```

The current suite has 14 tests covering real physics, camera output, deterministic
resets, native logs, idempotency, concurrency, transport reconnects, browser-route
checks, Cartesian movement, and the scripted manipulation baseline.

| Location | Responsibility |
| --- | --- |
| `src/abc_inspect/adapter.py` | ABC → Inspect embodiment and scorer |
| `src/abc_inspect/session.py` | Isolated rollout process and retry-safe command queue |
| `src/abc_inspect/server.py` | Shared MCP tools and server lifecycle |
| `src/abc_inspect/teleop.py` | Cartesian jog → actuator targets using Mink |
| `src/abc_inspect/play.py`, `play.html` | Local browser interface |
| `src/abc_inspect/client.py` | MCP protocol CLI helper |
| `src/abc_inspect/pick_place.py` | Privileged scripted baseline |
| `scripts/render_replay.py` | Recorded camera frames → browser replay |
| `outputs/` | Ignored local logs, frames, videos, and measurements |

Pinned upstream components:

- [ABC Sim](https://github.com/amazon-far/abc):
  `d0832d12651d1b260a652861a14648dc5f3660c7`, under ignored `vendor/abc`.
- [Inspect Robots](https://github.com/robocurve/inspect-robots):
  `d08442a9d1f43af4658c8d71e02d461e780286e1`, pinned in the uv configuration.
- Python 3.12, MuJoCo 3.8.1, and Mink; resolved packages are in `uv.lock`.

Bootstrap downloads robot/bottle assets with ABC's SHA256 verification. The cube
scene uses primitives and the shared robot assets. Upstream code and assets retain
their upstream licenses.

The server binds to localhost. Browser routes check Host and Origin, but there is
no authenticated controller identity. Local agents have shell access, so this is
a trusted development sandbox, not an isolated benchmark. See [ROADMAP.md](ROADMAP.md)
for the gates before making benchmark claims.
