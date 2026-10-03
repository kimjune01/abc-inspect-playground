#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
ABC_REV=d0832d12651d1b260a652861a14648dc5f3660c7
if [ ! -d vendor/abc/.git ]; then
  mkdir -p vendor
  git clone https://github.com/amazon-far/abc.git vendor/abc
fi
if [ "$(git -C vendor/abc rev-parse HEAD)" != "$ABC_REV" ]; then
  git -C vendor/abc fetch origin "$ABC_REV"
  git -C vendor/abc checkout --detach "$ABC_REV"
fi
uv sync --frozen --python 3.12
uv run python vendor/abc/prepare.py --sim-task put_plastic_bottles_in_bin
uv run python vendor/abc/prepare.py --sim-task spell_cat
