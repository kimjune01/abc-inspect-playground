# ABC Inspect prototype

Use `uv`. Write a failing behavior test before changing integration behavior;
commit each coherent change after its checks pass. Run `uv run pytest -q`,
`uv run ruff check src tests`, and `uv run mypy src/abc_inspect` as appropriate.

The user wants TUI subagents to operate the simulator. The shared localhost MCP
server has four tools documented in README.md. When its tools are not loaded,
`uv run python -m abc_inspect.client` is a real protocol client. View the returned
PNG files before choosing actions. Keep trial ownership explicit; all agents
share one active session. Reuse request ID and arguments after timeouts.

Inspect must own reset/step. Do not add direct qpos teleporting, evaluator reads
in live observations, or a second independent rollout loop. Never describe
harness completion as task success. The prototype's agents have shell access;
this is not an isolated benchmark environment.

Leave upstream vendor code unchanged. Do not edit the separate june.kim site.
Check port 8876 before starting a server; scripts/serve.sh does this. Evidence
belongs in outputs/. The checked-in project MCP config requires a new trusted
Codex project session; do not change global config or trust settings silently.
