# ABC + Inspect + MCP prototype

A working local integration spike for **ABC Sim → Inspect Robots → MCP → TUI agent**.
CPU MuJoCo physics and OpenGL cameras run on an Apple Silicon laptop. The simulator
needs no model weights, CUDA, physical robot, cloud simulator, or API key.
The agent still uses its usual model service.

See [DERISK.md](DERISK.md) for measured results and remaining research risks.

## Run

```sh
cd /Users/junekim/Documents/abc-inspect-prototype
bash scripts/bootstrap.sh  # pinned checkout, dependencies and one task's assets
uv run pytest -q
bash scripts/serve.sh      # shared MCP on http://127.0.0.1:8876/mcp
```

The server binds only to localhost. The launch script refuses to take over an
occupied port. Finish any trial before stopping the server with Ctrl-C.

`.codex/config.toml` registers this shared server as `abc_sim` for this project.
Start a new Codex session in this directory and check `/mcp`. Codex loads project
configuration only for trusted projects; the initial `codex mcp get abc_sim` here
reported no server before the project had been trusted. We have not changed global
Codex configuration or marked the project trusted automatically.
See the [official MCP setup](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

For a TUI session whose tool catalog is already loaded, the protocol helper works:

```sh
uv run python -m abc_inspect.client start_trial \
  '{"request_id":"trial-1","seed":7,"max_steps":100}'
```

It prints observation metadata and paths to three PNGs received through MCP.
An agent can view those images, then call tools with JSON arguments (or `@file.json`).
The tested subagent used this helper; native TUI tool discovery remains a separate
integration check for the next project session.

## Tools and contract

| Tool | Arguments | Result |
| --- | --- | --- |
| `start_trial` | `request_id`, `seed`, `max_steps` | Session ID, sequence 0, state, RGB images |
| `observe` | `session_id` | Latest completed state without advancing physics |
| `move_joints` | `session_id`, `request_id`, `expected_sequence`, `target`, `steps` | State after bounded physical movement |
| `finish_trial` | `session_id`, `request_id`, `expected_sequence`, `reason` | Final state, native Inspect JSON path, task metric |

`target` is 14 absolute values: **left six joint radians, left gripper, right six
joint radians, right gripper**. Grippers use 0 closed, 1 open. Actual joint limits
are returned by the server. Each request changes at most 0.2 radians per arm joint
and 0.25 per gripper, for 1–30 control ticks. The measured control rate is about 29.41 Hz (34 ms per tick).
The simulator pauses while the agent thinks.

Use a fresh request ID for each action and the latest returned `sequence`.
After a timeout, retry the **same ID and identical arguments**; do not send a fresh
motion. Duplicate responses may describe an older state, so observe again before
planning another action. Competing commands using the same sequence cannot both
execute. A server restart invalidates sessions; there is no crash recovery/replay.

One active trial and at most eight trials per server lifetime; each trial is
limited to 1–1000 control ticks, with a 15-minute idle timeout. HTTP disconnects
do not end the robot trial. All clients share the same server and must coordinate
ownership; sequence checks are concurrency control, not authentication.

## Inspect compatibility

The native `inspect_robots.eval` loop owns every reset and step. A queue-backed
`Policy` supplies `ActionChunk`s; the ABC adapter implements `Embodiment`; the
scorer consumes ABC's task evaluator. Each trial writes native JSON, `.npy` camera
frames, action metadata and an external-command transcript. The full external
agent conversation is **not** captured in that transcript.

`eval_status: success` means the harness completed; **`abc_success`** is the task
score. Saying “finished” cannot make the task successful. A finish command is a
logged no-motion control event; Inspect counts that event as a step, while
`physics_steps` excludes it. Budget exhaustion finishes automatically.

Render a native browser report (replace the path with `log_path`):

```sh
uv run inspect-robots view outputs/trials/SESSION/LOG.json --no-video -o outputs/report.html
```

The browser report is a replay viewer, not live browser teleoperation.

## Provenance and development

- [ABC](https://github.com/amazon-far/abc), pinned to
  `d0832d12651d1b260a652861a14648dc5f3660c7`, lives under ignored `vendor/abc`.
- [Inspect Robots](https://github.com/robocurve/inspect-robots), pinned to
  `d08442a9d1f43af4658c8d71e02d461e780286e1` in `pyproject.toml` and `uv.lock`.
- ABC's downloader verifies the selected assets with SHA256.
- Dependencies: `uv`; Python 3.12; MuJoCo 3.8.1. Only the bottles-and-bin task's
  asset bundles are downloaded. Upstream code/assets retain upstream licenses.

```sh
uv run pytest -q
uv run ruff check src tests
uv run mypy src/abc_inspect
```

`tests/` exercises real dynamics, images, seeded reset/replay, native logs,
retry/timeout/concurrency handling, action budgets and both MCP transports.
`outputs/` contains local evidence and logs and is intentionally ignored by git.

This is a trusted development sandbox. Benchmark isolation, useful manipulation
skills, broader seed validation, live browser UI and webcam teleoperation are
future gates, not established capabilities.

## Scripted pick-and-place demo

```sh
uv run python -m abc_inspect.pick_place --output outputs/pick-place/run
uv run python scripts/render_replay.py outputs/pick-place/run
```

The replay helper requires `ffmpeg`. Open the generated `outputs/demo/index.html`,
or serve that directory on localhost. The page contains only three camera views.

This controller uses **Mink IK and known initial object geometry**, with native
Inspect owning the rollout. It physically lifts a cube and releases it into ABC's
opaque box. It is a scripted baseline, not a vision-agent or MCP-driver result.
`pick_place=1` verifies the selected cube was lifted >12 cm, released with the
hand open, and counted inside the box by ABC. The independent `abc_success` score
can remain zero because ABC's sampled counting directive requires more objects.
The reproducibility test covers one fixed seed, not general task competence.

The controller checks grasp reachability and a sampled approach path on a separate
kinematic model. It sends only actuator targets to the real simulator. Coordinated
joint increments preserve the planned path; clipping each joint independently
caused the wrist camera to hit the box during development. Bottle grasps remain
unreliable and are not presented as successful.
