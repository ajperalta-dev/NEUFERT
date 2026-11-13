import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('NEUFERT_DATA_DIR', str(ROOT / 'data'))).resolve()
PRIVATE = DATA / 'private'
SOURCE = DATA / 'source' / 'neufert.pdf'
DB = PRIVATE / 'neufert.sqlite3'
MODEL = 'intfloat/multilingual-e5-small'
VERSION = '1.0.0'
os.environ.setdefault('HF_HOME', str(PRIVATE / 'models'))
os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')

