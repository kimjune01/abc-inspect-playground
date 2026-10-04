# Roadmap

Turn the local playground into a reproducible benchmark for TUI agents, reusing
ABC, MuJoCo, Inspect, Mink, and MCP. Work through these stages in order.

## Current prototype

Six ABC tasks across two scenes, Chrome teleoperation, five retry-safe MCP tools,
and native Inspect logs and scores. A privileged scripted pick-and-place and a
TUI subagent motion trial work. The 37 tests validate integration, not general
manipulation ability or benchmark validity. See [README](README.md) for setup and
[DERISK](DERISK.md) for earlier measurements.

## 1. Make manual control useful

- Add a ready pose, wrist tilt, and fine/coarse motion; show IK reach limits.
- Measure command-to-image latency and actual movement before optimizing.
- Verify release, Escape, lost focus, and reconnects stop unintended commands.
- Define disk-log retention; session memory and worker lifetimes are already bounded.

**Gate:** record camera-only manual pick-and-place across a declared seed set,
including failures, stop behavior, and latency. This is the next concrete slice.

## 2. Make agent handoff dependable

- Verify native MCP discovery in a fresh trusted TUI project session.
- Add explicit human/agent ownership and browser viewing of agent trials.
- Complete a camera-grounded agent episode without privileged object geometry.
- Surface idle expiry and worker failure; use a new trial after a crash.
- Bound agent turns, physics ticks, wall time, and retained output separately.

**Gate:** a recorded agent attempt, safe human takeover, and retries without
duplicated motion. Report task success separately from successful tool use.

## 3. Specify one benchmark

Choose the research question after observing human and agent failures. Recovery
from a failed grasp is one candidate.

- Declare the task, scorer, cameras, robot state, tools, seeds, budgets, and reset/
  termination rules. State what the IK layer solves for the agent.
- Distinguish policy failure, scorer failure, collisions, and invalid runs.
- Establish human, camera-only agent, and privileged scripted baselines with their
  different information and action conditions disclosed.

**Gate:** publish the specification and successful/failed Inspect logs. Check that
scoring rejects misleading completions and transient placements.

## 4. Make comparisons reproducible

- Isolate agents from simulator internals, evaluators, logs, and unrestricted shell.
- Hold out evaluation seeds and test placement/geometry variation.
- Record model versions, prompts, tool schemas, settings, dependencies, control
  parameters, and full agent transcripts.
- Add batch results with uncertainty, failure breakdowns, time, and inference cost.
- Check scorer stability, replay tolerance, and a second machine.

**Gate:** another person reproduces the evaluation; agents cannot read hidden
state or modify scoring. Keep Inspect's existing recording format.

## Optional: laptop-camera control

After keyboard control works, try local hand tracking with relative motion,
calibration, smoothing, and an explicit engage gesture. Stop on tracking loss;
handle hand swaps and occlusion. Use the same MCP/Inspect command path.

**Gate:** compare latency, tracking-loss behavior, and task completion with keyboard control.

## Defer

Hardware, policy training, larger task catalogs, concurrent controllers, cloud
hosting, and durable crash replay until the current benchmark needs them.
