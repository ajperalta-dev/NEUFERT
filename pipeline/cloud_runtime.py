"""Provision immutable book data and persist user changes through the state service."""
import asyncio
import gzip
import json
import os
import shutil
import sqlite3
from pathlib import Path


def provision():
    seed = Path(__file__).parent / 'deployment-data' / 'private'
    if not (seed / 'neufert.sqlite3.gz').is_file():
        raise RuntimeError('Deployment data missing: run python -m pipeline.prepare_deployment')
    data = Path(os.environ.setdefault('NEUFERT_DATA_DIR', '/tmp/neufert'))
    private = data / 'private'
    private.mkdir(parents=True, exist_ok=True)
    db = private / 'neufert.sqlite3'
    if not db.exists():
        temporary = db.with_suffix('.tmp')
        with gzip.open(seed / 'neufert.sqlite3.gz', 'rb') as src, temporary.open('wb') as dst:
            shutil.copyfileobj(src, dst)
        temporary.replace(db)
    # Book assets remain in the image; SQLite and user changes live in writable cache.
    for item in seed.iterdir():
        if item.name == 'neufert.sqlite3.gz': continue
        target = private / item.name
        if not target.exists(): target.symlink_to(item, target_is_directory=item.is_dir())


def snapshot(db):
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        collections = []
        for row in c.execute('SELECT * FROM collections ORDER BY id'):
            collection = dict(row)
            collection['entries'] = [r[0] for r in c.execute(
                'SELECT entry_id FROM collection_entries WHERE collection_id=? ORDER BY entry_id', (row['id'],))]
            collections.append(collection)
        return {'collections': collections, 'reviewed': [r[0] for r in c.execute('SELECT id FROM entries WHERE review=0 ORDER BY id')]}


def restore(db, state):
    with sqlite3.connect(db) as c:
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('DELETE FROM collection_entries')
        c.execute('DELETE FROM collections')
        for item in state['collections']:
            c.execute('INSERT INTO collections(id,name,created) VALUES(?,?,?)', (item['id'], item['name'], item.get('created')))
            c.executemany('INSERT INTO collection_entries VALUES(?,?)', [(item['id'], eid) for eid in item['entries']])
        c.execute('UPDATE entries SET review=1')
        c.executemany('UPDATE entries SET review=0 WHERE id=?', [(eid,) for eid in state['reviewed']])


def install_persistence(app):
    import httpx
    from starlette.responses import JSONResponse
    from .config import DB
    base = os.environ['NEUFERT_STATE_URL'].rstrip('/')
    lock = asyncio.Lock()
    initial = snapshot(DB)

    @app.middleware('http')
    async def durable_state(request, call_next):
        if request.url.path.startswith('/api/assets/') or request.url.path == '/api/status':
            return await call_next(request)
        async with lock:
            async with httpx.AsyncClient(timeout=30) as client:
                try:
                    result = await client.get(base + '/state')
                    if result.status_code == 404:
                        current, etag = initial, None
                    else:
                        result.raise_for_status()
                        current, etag = result.json(), result.headers['etag']
                    restore(DB, current)
                except Exception:
                    return JSONResponse({'detail': 'Durable state unavailable'}, status_code=503)
                response = await call_next(request)
                if request.method not in ('GET', 'HEAD', 'OPTIONS'):
                    updated = snapshot(DB)
                    if updated != current:
                        if response.status_code >= 400:
                            restore(DB, current)
                            return response
                        try:
                            saved = await client.put(base + '/state', json=updated,
                                headers={'If-Match': etag} if etag else {})
                            saved.raise_for_status()
                        except Exception:
                            restore(DB, current)
                            return JSONResponse({'detail': 'Changes were not saved. Retry the operation.'},
                                status_code=409 if 'saved' in locals() and saved.status_code == 409 else 503)
                return response
