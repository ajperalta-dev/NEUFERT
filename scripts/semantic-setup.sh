#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export NEUFERT_DATA_DIR="${NEUFERT_DATA_DIR:-$PWD/data}"
# Fail fast on policy/connection errors, without repeated model-library retries.
curl -fI --max-time 30 https://huggingface.co/intfloat/multilingual-e5-small/resolve/main/config.json >/dev/null
.venv/bin/pip install --cache-dir "${PIP_CACHE_DIR:-/tmp/neufert-pip}" 'torch==2.15.0+cpu' --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install --cache-dir "${PIP_CACHE_DIR:-/tmp/neufert-pip}" -r pipeline/requirements-semantic.txt
.venv/bin/python -m pipeline.semantic --download
