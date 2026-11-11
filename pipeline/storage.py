import json
import os
import sqlite3
from pathlib import Path
import sqlite_vec

MODEL = 'intfloat/multilingual-e5-small'
DIM = 384

def data_dir():
    return Path(os.environ.get('NEUFERT_DATA_DIR', '/data')).resolve()

def private_dir():
    path = data_dir() / 'private'
    path.mkdir(parents=True, exist_ok=True)
    return path

def connect():
    db = sqlite3.connect(private_dir() / 'neufert.sqlite3', timeout=30, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    db.executescript('''
    PRAGMA journal_mode=WAL;
    PRAGMA foreign_keys=ON;
    CREATE TABLE IF NOT EXISTS documents (
        id TEXT PRIMARY KEY, filename TEXT NOT NULL, page_count INTEGER NOT NULL,
        metadata TEXT NOT NULL, pipeline_version TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS pages (
        document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        number INTEGER NOT NULL, printed TEXT, width REAL, height REAL,
        text TEXT NOT NULL, blocks TEXT NOT NULL, image TEXT NOT NULL,
        tables_json TEXT NOT NULL, ocr INTEGER NOT NULL, status TEXT NOT NULL,
        PRIMARY KEY(document_id, number)
    );
    CREATE TABLE IF NOT EXISTS entries (
        id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        page_pdf INTEGER NOT NULL, page_printed TEXT, title_de TEXT NOT NULL,
        title_es TEXT NOT NULL, title_en TEXT NOT NULL, typology TEXT NOT NULL,
        spaces TEXT NOT NULL, dimensions TEXT NOT NULL, activities TEXT NOT NULL,
        equipment TEXT NOT NULL, bbox TEXT NOT NULL, figures TEXT NOT NULL,
        text TEXT NOT NULL, confidence REAL NOT NULL, needs_review INTEGER NOT NULL,
        reviewed INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS entries_page ON entries(document_id,page_pdf);
    CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
        id UNINDEXED, title, text, tags, tokenize='unicode61 remove_diacritics 2'
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS entry_vectors USING vec0(
        entry_id TEXT PRIMARY KEY, embedding float[384]
    );
    CREATE TABLE IF NOT EXISTS vector_metadata (
        entry_id TEXT PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE, model TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS collections (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS collection_entries (
        collection_id TEXT REFERENCES collections(id) ON DELETE CASCADE,
        entry_id TEXT REFERENCES entries(id) ON DELETE CASCADE,
        PRIMARY KEY(collection_id,entry_id)
    );
    CREATE TABLE IF NOT EXISTS favorites (
        entry_id TEXT PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE
    );
    ''')
    return db

def decode(row):
    item = dict(row)
    for field in ['spaces', 'dimensions', 'activities', 'equipment', 'bbox', 'figures']:
        if field in item:
            item[field] = json.loads(item[field])
    return item

def save_entry(db, item):
    fields = list(item)
    values = [json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for v in item.values()]
    db.execute(f"INSERT INTO entries ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)}) ON CONFLICT(id) DO UPDATE SET {','.join((f'{f}=CASE WHEN entries.reviewed=1 THEN 0 ELSE excluded.needs_review END' if f == 'needs_review' else f'{f}=excluded.{f}') for f in fields if f != 'id')}", values)
    tags = ' '.join([item['title_es'], item['title_en'], item['typology'], *item['spaces'], *item['equipment'], *item['activities']])
    db.execute('INSERT INTO entries_fts(id,title,text,tags) VALUES (?,?,?,?)',
               (item['id'], item['title_de'], item['text'], tags))
