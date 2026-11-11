#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export NEUFERT_DATA_DIR="${NEUFERT_DATA_DIR:-$PWD/data}"
# Local processes only. No credentials are exposed to the browser.
.venv/bin/python -m uvicorn pipeline.api:app --host 127.0.0.1 --port 8000 &
api_pid=$!
cleanup() { kill "$api_pid" "${web_pid:-}" 2>/dev/null || true; wait "$api_pid" "${web_pid:-}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
npm run dev --prefix app &
web_pid=$!
wait -n "$api_pid" "$web_pid"
