#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export NEUFERT_DATA_DIR="${NEUFERT_DATA_DIR:-$PWD/data}"
mkdir -p "$NEUFERT_DATA_DIR/source" "$NEUFERT_DATA_DIR/private/tessdata"
python3 -m venv .venv
.venv/bin/pip install --cache-dir "${PIP_CACHE_DIR:-/tmp/neufert-pip}" -r pipeline/requirements.txt
npm ci --prefix app --cache "${npm_config_cache:-/tmp/neufert-npm}" --no-audit --no-fund
# Official immutable Tesseract training artifact; never disable TLS or checksum checks.
training="$NEUFERT_DATA_DIR/private/tessdata/deu.traineddata"
if ! echo "19d219bbb6672c869d20a9636c6816a81eb9a71796cb93ebe0cb1530e2cdb22d  $training" | sha256sum --check --status; then
  curl -fL --max-time 120 https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/87416418657359cb625c412a48b6e1d6d41c29bd/deu.traineddata -o "$training.part"
  echo "19d219bbb6672c869d20a9636c6816a81eb9a71796cb93ebe0cb1530e2cdb22d  $training.part" | sha256sum --check
  mv "$training.part" "$training"
fi
.venv/bin/python -m pytest pipeline/tests -q
npm run build --prefix app
