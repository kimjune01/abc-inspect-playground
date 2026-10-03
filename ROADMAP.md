# Roadmap

Build an inexpensive robotics playground that can become a reproducible,
Inspect-compatible benchmark for TUI agents. Keep ABC, MuJoCo, Inspect, Mink, and
MCP as the standard components; add only the adapters and controls needed to connect
them. Physical hardware is outside the current scope.

This is a proposed sequence, not a delivery schedule. Complete each gate before
using the next stage to draw research conclusions.

## What works now

- Local CPU physics and three rendered cameras on the tested Apple Silicon laptop.
- Chrome keyboard control: XYZ translation, yaw, gripper, arm selection, and reset.
- Five shared MCP tools with serialized commands, sequence checks, and safe retries.
- Native Inspect rollouts, action/frame records, and simulator-based scoring.
- Two scene tabs with six documented ABC tasks and an explicit Evaluate button.
- One successful scripted cube pick-and-place with privileged initial geometry.
- A TUI subagent motion trial through a real MCP protocol client.

The 35-test suite validates integration behavior. It does not establish general
manipulation ability, low-latency teleoperation, or benchmark validity.
[DERISK.md](DERISK.md) preserves the earlier integration measurements; its list of
unfinished features predates the live controls and scripted baseline.

## 1. Make manual manipulation useful

**Outcome:** someone can pick up and place an object using only the browser.

- Add a reachable ready pose and wrist-tilt control or a clear top-down grasp mode.
  XYZ plus yaw currently preserves the initial tilt, which limits tabletop grasps.
- Add fine/coarse motion control and visible feedback when IK reaches a limit.
- Measure command-to-image latency and achieved movement; separate IK time,
  physics/render time, image encoding, and transport time before optimizing.
- Verify held keys, release, Escape, lost focus, errors, and reconnects do not queue
  unintended motion. Keep the interface small.
- Define disk-log retention. Navigation now keeps eight recent sessions and
  permits 256 starts per server run; retry images live on disk, and finished
  trials release worker resources.

**Gate:** record manual pick-and-place across a declared small seed set, report
successes and failures, and measure stop behavior and latency. Do not require a
perfect success rate to proceed, but explain the failures.

**Reuse:** existing Mink kinematics, ABC actuators, browser events, and Inspect logs.

## 2. Make agent control and handoff dependable

**Outcome:** a TUI subagent can acquire a trial, act, and return control to a human.

- Verify native MCP tool discovery in a fresh trusted project session.
- Define controller ownership and an explicit human/agent handoff. Sequence checks
  prevent stale writes but do not decide who is allowed to act.
- Show current controller and trial status in Chrome. Let an agent trial be viewed
  from the browser without granting accidental control.
- Complete a camera-grounded agent episode through `observe` and `jog_arm`, with
  no access to initial object geometry. Keep the privileged script as a separate baseline.
- Surface idle expiry and worker failure promptly, and define what recovery means.
  Start a new trial after a crash until durable recovery is explicitly implemented.
- Bound agent turns, physics ticks, wall time, and retained output independently.

**Gate:** a subagent completes a recorded attempt using the intended tools; a
human takes over safely; reconnect/retry tests show no duplicated motion. Report
actual manipulation success separately from successful tool use.

**Reuse:** the current MCP client/server, session queue, and native Inspect policy.
Do not build a second simulation loop for the agent.

## 3. Define the first benchmark

**Outcome:** one narrow, interpretable task with an honest success criterion.

Start with a candidate such as **recovering from a failed cube grasp using RGB
feedback and Cartesian jogs**. Select the research question after observing manual
and agent failures; this candidate is not yet a settled benchmark design.

- Decide whether the primary measurement is perception, planning, recovery, or
  motor control. State what the IK layer solves on the agent's behalf.
- Specify each benchmark's instruction, scene, target, and scorer. The browser now
  aligns six ABC task directives with their native evaluators and final Inspect
  scores; future tasks need the same alignment.
- Specify exactly which cameras, robot state, and tools the agent receives.
- Fix physics and action budgets, reset semantics, seeds, and termination rules.
  Track wall time separately because simulation pauses during reasoning.
- Define success, partial progress, collision/failure categories, and invalid runs.
  Report scorer failures separately from policy failures.
- Establish human, privileged scripted, and camera-only agent baselines under
  clearly disclosed information/action conditions. Avoid presenting them as equal
  inputs when the script receives object geometry.

**Gate:** publish a task specification and representative successful and failed
Inspect logs. The scorer must reject misleading completions such as “finished”
without a placed object, or an object briefly passing through the target area.

## 4. Make comparisons reproducible and resistant to leakage

**Outcome:** results can support a model comparison rather than a demo claim.

- Isolate the agent from simulator internals, evaluator state, output directories,
  and unrestricted shell access. Expose only the declared tool surface.
- Separate development seeds from held-out episodes. Test variation in object
  placement and geometry before claiming generalization.
- Record model/provider version, prompts, tool definitions, sampling settings,
  dependencies, controller parameters, seeds, and the full agent transcript.
- Add batch evaluation and summaries with trial counts, uncertainty, failure
  breakdowns, wall/simulated time, and inference cost when available.
- Check scorer stability, repeated runs, cross-process replay tolerance, and
  performance on at least one additional machine.

**Gate:** another person can reproduce the evaluation from documented setup and
artifacts; the agent cannot read hidden task state or modify the evaluator.

**Reuse:** Inspect's evaluation and logging interfaces and the existing dependency
pins. Extend these rather than inventing a separate results format.

## Optional track: laptop-camera teleoperation

Begin after manual control and latency are understood. This can help collect human
trajectories, but is not a prerequisite for an agent benchmark.

- Prototype browser hand tracking using an existing maintained implementation.
- Map relative hand motion to bounded Cartesian deltas with calibration, smoothing,
  dead zones, and an explicit engage/disengage gesture or held key.
- Stop commands when tracking is lost. Handle hand swaps, occlusion, jitter, and
  accidental gestures before enabling gripper control.
- Keep camera processing local where feasible and make capture state obvious.
- Send movement through the same MCP/Inspect path as keyboard and agent control.

**Gate:** measure latency and tracking-loss behavior, and compare task completion
against keyboard control. Keep it optional if it adds friction or unreliable input.

## Work to defer

- Physical robots and sim-to-real transfer until a simulation task is useful.
- Training large vision-action models or adding GPU requirements.
- Broad task catalogs before one task has sound instructions, scoring, and baselines.
- Simultaneous multi-agent control before explicit ownership works.
- Cloud hosting, remote access, and durable crash replay without a concrete need.

## Next concrete slice

Add a ready pose and wrist tilt, then record a manual cube pick-and-place using
only the visible cameras. This tests whether the action interface is sufficient
before attributing manipulation failures to an agent.
