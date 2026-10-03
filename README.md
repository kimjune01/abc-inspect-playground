# ABC Inspect prototype

A local integration spike for ABC Sim, Inspect Robots, and stateful MCP control.
The first gate uses one unmodified ABC bottles-and-bin scene with CPU MuJoCo
physics and standard camera rendering on an Apple Silicon Mac. No model weights,
CUDA, training stack, physical robots, or cloud services are needed for this gate.

## Setup

```sh
bash scripts/bootstrap.sh
uv run pytest -q
```

ABC is checked out under ignored `vendor/abc`, pinned to
`d0832d12651d1b260a652861a14648dc5f3660c7`. Inspect Robots is pinned to
`d08442a9d1f43af4658c8d71e02d461e780286e1` in `pyproject.toml` and `uv.lock`.
Upstream asset downloads are SHA256-verified by ABC's own downloader.

## Planned gates

- Real camera pixels, actuator-driven physics, reproducible initial scene.
- Inspect embodiment adapter and a real evaluation log.
- Stateful MCP action requests with retry deduplication and stale-state rejection.
- One subagent observes a camera frame, commands a motion, and inspects the log.

This is a development sandbox, not a validated robotics benchmark. World editing,
checkpoint restoration, webcam control, policy inference and browser UI are outside
this first spike. Do not infer sim-to-real validity from a successful integration.
