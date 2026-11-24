"""ASGI entrypoint when the service working directory is pipeline/."""
import os
import sys
from pathlib import Path

# Existing modules use package-relative imports (pipeline.db, pipeline.search, ...).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if os.getenv('NEUFERT_CLOUD') == '1':
    from pipeline.cloud_runtime import provision
    provision()

if os.getenv('VERCEL'):
    data = os.getenv('NEUFERT_DATA_DIR')
    if not data or not (Path(data) / 'private' / 'neufert.sqlite3').is_file():
        raise RuntimeError(
            'Neufert data is not provisioned. Configure NEUFERT_DATA_DIR with the '
            'prepared database and assets before starting the deployed API. '
            'An empty replacement database will not be created.'
        )

from pipeline.api import app  # noqa: E402,F401

if os.getenv('NEUFERT_CLOUD') == '1':
    from pipeline.cloud_runtime import install_persistence
    install_persistence(app)
