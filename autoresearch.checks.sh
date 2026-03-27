#!/bin/bash
set -euo pipefail

pytest_log=$(mktemp)
ruff_log=$(mktemp)
ty_log=$(mktemp)
trap 'rm -f "$pytest_log" "$ruff_log" "$ty_log"' EXIT

if ! uv run pytest -q >"$pytest_log" 2>&1; then
  tail -80 "$pytest_log"
  exit 1
fi

if ! uv run ruff check . >"$ruff_log" 2>&1; then
  tail -80 "$ruff_log"
  exit 1
fi

if ! uv run ty check >"$ty_log" 2>&1; then
  tail -80 "$ty_log"
  exit 1
fi
