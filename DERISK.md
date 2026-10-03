# Derisking result — 2026-10-03

**Proceed to a manipulation baseline.** ABC, native Inspect evaluation and stateful
MCP work together locally, and a TUI subagent has driven a real trial through the
MCP protocol. This removes the basic integration uncertainty. It does not yet
establish a useful robotics benchmark or browser/webcam control.

## Evidence

Test machine: Apple M3, 16 GiB RAM, macOS arm64, Python 3.12.12, MuJoCo 3.8.1.
Task: ABC `put_plastic_bottles_in_bin`, three 224×168 RGB cameras.

| Gate | Result |
| --- | --- |
| Laptop physics and images | Passed: actual MuJoCo actuator dynamics and all three cameras |
| Seeded reset | Passed: reset explicitly restores arm pose; repeated seeded state/image checks |
| Repeated trajectory | Passed: two fresh processes, same seed/actions, matching joints within tolerance |
| Native Inspect integration | Passed: `eval` owns rollout, real JSON/actions/frame arrays and simulator scoring |
| Retry after response timeout | Passed: simulated response timeout; identical retry does not resubmit motion |
| Concurrent writers | Passed: one of two commands from the same sequence executes; other is stale |
| Bounds and budget | Passed: oversized commands rejected; budget exhaustion finalizes log |
| stdio and HTTP MCP | Passed: real SDK clients, image decoding, reconnects and completion |
| TUI subagent | Passed via protocol CLI helper, not newly discovered native TUI tools |
| Pick-and-place success | Not attempted; task score correctly zero |

**11 tests passed**, plus Ruff and mypy. Tests are integration checks on real ABC,
not a mocked environment. Git commits preserve each implementation gate.

[Subagent evidence](outputs/agent-test/RESULTS.md),
[before image](outputs/agent-test/28b10bc0aadb43cba731327b39daf5bc/0000-top.png),
[after image](outputs/agent-test/28b10bc0aadb43cba731327b39daf5bc/0001-top.png),
and [native Inspect browser report](outputs/report.html) are saved locally.
Evidence files are intentionally untracked. Native log:
`outputs/trials/28b10bc0aadb43cba731327b39daf5bc/abc-mcp-spike_f39e1ada.json`.

## Measured cost of one short trial

| Measurement | Observed |
| --- | ---: |
| Start trial RPC | 1.391 s |
| Five control ticks + three image responses | 0.487 s wall time |
| Same request retried | 0.044 s, zero further physics |
| Finish and write native log | 0.049 s |
| Simulated time advanced | 0.170 s |
| Requested / achieved joint0 change | +0.050 / +0.04767 rad |
| Child process peak resident memory | 1.93 GB / 1.80 GiB |
| Installed Python environment | 215 MiB on disk |
| ABC checkout including selected downloaded assets | 285 MiB on disk |

These are individual observations, not a latency distribution or minimum machine
specification. Peak memory excludes the parent MCP server, TUI and other programs.
Disk figures exclude shared uv caches and the separately installed Python runtime.
No policy model was loaded. CPU physics uses the laptop's graphics stack for cameras.
The 0.487 s motion call is slower than its 0.170 s of simulated time at this setting;
paused action chunks are usable, but these measurements do not prove real-time teleop.

## Failures found before building further

1. **ABC reset keeps the current arm pose.** Calling reset with the same seed is
   insufficient after motion. The adapter calls upstream `forget_arm_state()` before
   reset, and a regression checks restoration after movement.
2. **HTTP connection lifetime is not robot-trial lifetime.** Our initial FastMCP
   cleanup ended the trial when the one-call client disconnected. The subagent's
   motion then failed with “Session finished.” Cleanup now belongs to the HTTP app's
   shutdown, and a regression starts, observes, moves and finishes across distinct
   client connections.
3. **ABC's generic Gym bounds do not describe its actual joint commands.** The
   adapter gets actuator ranges from the MuJoCo model and handles normalized grippers.
   The MCP surface applies additional per-command limits.
4. **A completed harness run is not task success.** Inspect can report `success`
   while `abc_success` is zero. Finishing is logged separately without moving the arm.

## Remaining risks and next gates

- **Can the interface solve anything?** Establish one successful grasp/place with
  a fixed controller or teleop baseline before using agent failures as research
  evidence. Joint nudges prove transport and dynamics, not manipulation. Borrow
  an existing controller/IK implementation; keep its action/observation contract fixed.
- **What is being benchmarked?** Choose whether the target is planning, perception,
  recovery, or motor control. Publish which conveniences a controller provides.
  Fix action budget, seeds and observations before comparing agents.
- **Isolation and scorer leakage.** Live MCP observations expose RGB and robot
  proprioception, not object poses or task scores. However, local TUI agents retain
  shell access to code, files and the simulator. This is a cooperative sandbox.
  A benchmark needs an isolated agent process with only the intended tool surface,
  separate evaluator access, and held-out episodes.
- **Clock and transcript comparability.** Simulation pauses during reasoning.
  Record both wall and simulated time; do not compare paused results to a live robot
  without qualification. Inspect currently captures external tool commands, not
  complete agent prompts/context. Add that provenance for model comparisons.
- **Operational recovery.** Commands serialize and deduplicate within one server
  lifetime. There is no durable journal, checkpoint restore, authenticated ownership,
  or tested crash recovery. Abrupt process failure invalidates sessions. Idle expiry
  finalizes the worker trial; its final response is collected on the next command.
- **TUI/browser/webcam ergonomics.** A project-local MCP config is prepared, but
  direct discovery in a new trusted TUI session remains to be checked. The HTML
  artifact is a native Inspect replay report. Live browser controls and laptop-camera
  hand tracking are separate work; test tracking jitter and control latency before
  adding them to benchmark conditions.

## Related work to reuse

The prior-art search identified neighboring implementations, not a verified exact
ABC + Inspect + MCP stack. This is not a novelty claim.

- [ABC](https://github.com/amazon-far/abc): the simulator, task assets and evaluator
  used here, unchanged.
- [Inspect Robots](https://github.com/robocurve/inspect-robots): the real rollout,
  action/observation types, logger, scorer interface and replay viewer used here.
- [mujoco-arm-mcp](https://github.com/kevinave/mujoco-arm-mcp): a small Codex/MCP arm
  example. The inspected simple arm path sets joint positions directly; this spike
  instead drives actuator targets through MuJoCo steps.
- [mujoco-mcp-server](https://github.com/Rongxuan-Zhou/mujoco-mcp-server): a broader
  MuJoCo tool server with scene/control/rendering utilities, worth reviewing before
  implementing IK or more tools.
- [Dimensional agentic manipulation](https://docs.dimensional.org/capabilities/manipulation/agentic/):
  another relevant agent-to-manipulation integration pattern.

The deliberate custom code here is the ABC/Inspect adapter, queued external policy,
small session protocol and four MCP tools. The simulator and evaluation machinery
remain standard upstream components.
