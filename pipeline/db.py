import sqlite3
from .config import DB

SCHEMA = '''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, name TEXT, language TEXT, edition TEXT, pages INTEGER, metadata TEXT, outline TEXT);
CREATE TABLE IF NOT EXISTS pages(id TEXT PRIMARY KEY, document_id TEXT REFERENCES documents(id), number INTEGER, printed TEXT, width REAL, height REAL, text TEXT, blocks TEXT, tables_json TEXT, image TEXT, version TEXT, UNIQUE(document_id,number));
CREATE TABLE IF NOT EXISTS entries(id TEXT PRIMARY KEY, page_id TEXT REFERENCES pages(id) ON DELETE CASCADE, title TEXT, title_de TEXT, title_es TEXT, title_en TEXT, text TEXT, bbox TEXT, confidence REAL, review INTEGER DEFAULT 1, section TEXT);
CREATE TABLE IF NOT EXISTS figures(id TEXT PRIMARY KEY, entry_id TEXT REFERENCES entries(id) ON DELETE CASCADE, bbox TEXT, image TEXT, method TEXT);
CREATE TABLE IF NOT EXISTS dimensions(id INTEGER PRIMARY KEY, entry_id TEXT REFERENCES entries(id) ON DELETE CASCADE, name TEXT, value REAL, unit TEXT, context TEXT, metres REAL);
CREATE TABLE IF NOT EXISTS tags(entry_id TEXT REFERENCES entries(id) ON DELETE CASCADE, kind TEXT, value TEXT, PRIMARY KEY(entry_id,kind,value));
CREATE TABLE IF NOT EXISTS embedding_chunks(id INTEGER PRIMARY KEY, entry_id TEXT REFERENCES entries(id) ON DELETE CASCADE, chunk_index INTEGER, model TEXT, UNIQUE(entry_id,chunk_index,model));
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(id UNINDEXED, title, text, tags, tokenize='unicode61 remove_diacritics 2');
CREATE TABLE IF NOT EXISTS collections(id TEXT PRIMARY KEY, name TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS collection_entries(collection_id TEXT REFERENCES collections(id) ON DELETE CASCADE, entry_id TEXT REFERENCES entries(id) ON DELETE CASCADE, PRIMARY KEY(collection_id,entry_id));
INSERT OR IGNORE INTO collections(id,name) VALUES('favorites','Favoritos');
CREATE INDEX IF NOT EXISTS entry_page ON entries(page_id);
CREATE INDEX IF NOT EXISTS tag_filter ON tags(kind,value,entry_id);
CREATE INDEX IF NOT EXISTS dimension_filter ON dimensions(metres,entry_id);
'''

def connect(path=None, vectors=False):
    path = path or DB
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    if vectors:
        import sqlite_vec
        con.enable_load_extension(True)
        sqlite_vec.load(con)
        con.enable_load_extension(False)
    return con

def initialize(path=None):
    with connect(path, vectors=True) as con:
        con.executescript(SCHEMA)
        con.execute('CREATE VIRTUAL TABLE IF NOT EXISTS vectors USING vec0(embedding float[384])')

