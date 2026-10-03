#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if lsof -ti:8876 >/dev/null; then
  echo 'Port 8876 is already in use. Reuse the existing ABC server or stop it first.' >&2
  exit 1
fi
exec uv run python -m abc_inspect.server --transport streamable-http --port 8876
