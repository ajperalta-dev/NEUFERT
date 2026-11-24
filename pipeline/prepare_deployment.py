"""Copy runtime book assets and a consistent SQLite backup, never the source PDF or secrets."""
import gzip
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from .config import PRIVATE, MODEL


def prepare():
    destination = Path(__file__).parent / 'deployment-data'
    private = destination / 'private'
    private.mkdir(parents=True, exist_ok=True)
    # SQLite backup includes committed WAL contents without modifying the source.
    temporary = PRIVATE / 'deployment-backup.sqlite3'
    with sqlite3.connect(PRIVATE / 'neufert.sqlite3') as src, sqlite3.connect(temporary) as dst:
        src.backup(dst)
        assert dst.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    with temporary.open('rb') as src, (private / 'neufert.sqlite3.gz').open('wb') as raw:
        with gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as dst:
            shutil.copyfileobj(src, dst)
    files = {p for p in PRIVATE.rglob('*') if p.is_file() and p.suffix.lower() in ('.webp', '.png', '.jpg', '.jpeg')}
    for directory in ['base-package', 'fichas', 'entries']:
        files.update(p for p in (PRIVATE / directory).rglob('*') if p.is_file() and p.suffix in ('.json', '.txt', '.md'))
    for directory in ['reports', 'pass2-runs']:
        files.update(p for p in (PRIVATE / directory).rglob('*') if p.is_file() and p.suffix in ('.html', '.json', '.csv'))
    manifest = []
    for source in sorted(files):
        relative = source.relative_to(PRIVATE)
        target = private / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.read_bytes() != source.read_bytes(): shutil.copyfile(source, target)
        manifest.append({'path': relative.as_posix(), 'bytes': target.stat().st_size,
                         'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    revision = (PRIVATE / 'models' / 'hub' / ('models--' + MODEL.replace('/', '--')) / 'refs/main').read_text().strip()
    (destination / 'model.json').write_text(json.dumps({'model': MODEL, 'revision': revision}, indent=2)+'\n')
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(json.dumps({'files': len(files), 'images': sum(p.suffix.lower() in ('.webp','.png','.jpg','.jpeg') for p in files),
                      'bytes': sum(x['bytes'] for x in manifest), 'database_gzip_bytes': (private/'neufert.sqlite3.gz').stat().st_size}))

if __name__ == '__main__': prepare()
