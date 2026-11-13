"""Additive migration for prepared pages and new architectural fichas."""
import hashlib
import json
from datetime import datetime, timezone
from .config import PRIVATE, MODEL
from .db import connect

DIMS=384
DDL=f'''
CREATE TABLE IF NOT EXISTS toc(document_id TEXT,id TEXT,title TEXT,level INTEGER,pdf_page INTEGER,pdf_end INTEGER,book_page INTEGER,PRIMARY KEY(document_id,id));
CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(page_id UNINDEXED,text,chapter,section,tokenize='unicode61 remove_diacritics 2');
CREATE TABLE IF NOT EXISTS embeddings(rowid INTEGER PRIMARY KEY,entidad TEXT NOT NULL,id_entidad TEXT NOT NULL,modelo TEXT NOT NULL CHECK(modelo='{MODEL}'),dimensiones INTEGER NOT NULL CHECK(dimensiones=384),vector BLOB NOT NULL CHECK(length(vector)=1536),source_hash TEXT NOT NULL,UNIQUE(entidad,id_entidad));
CREATE VIRTUAL TABLE IF NOT EXISTS entity_vectors USING vec0(embedding float[384] distance_metric=l2);
CREATE TABLE IF NOT EXISTS fichas(id TEXT PRIMARY KEY,page_id TEXT NOT NULL REFERENCES pages(id),payload TEXT NOT NULL,source_hash TEXT NOT NULL,model TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS vision_progress(page_id TEXT PRIMARY KEY,source_hash TEXT,model TEXT,status TEXT,input_tokens INTEGER,output_tokens INTEGER,updated TEXT);
CREATE TABLE IF NOT EXISTS structured_migrations(version INTEGER PRIMARY KEY,applied TEXT);
'''

def contract(con):
    models={r[0] for r in con.execute('SELECT DISTINCT model FROM embedding_chunks')}
    sql=con.execute("SELECT sql FROM sqlite_master WHERE name='vectors'").fetchone()
    if models!={MODEL} or not sql or 'float[384]' not in sql[0]:raise ValueError('Existing embedding contract does not match; refusing migration')
    blob=con.execute('SELECT embedding FROM vectors LIMIT 1').fetchone()[0]
    rows=con.execute('SELECT rowid,distance FROM vectors WHERE embedding MATCH ? AND k=3 ORDER BY distance',(blob,)).fetchall()
    for row in rows:
        expected=con.execute('SELECT vec_distance_L2(embedding,?) FROM vectors WHERE rowid=?',(blob,row['rowid'])).fetchone()[0]
        if abs(expected-row['distance'])>1e-5:raise ValueError('Existing distance metric is not L2')

def migrate():
    with connect(vectors=True) as con:
        contract(con)
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='structured_migrations'").fetchone():
            import sqlite3
            backup=PRIVATE/'before-structured.sqlite3'
            if not backup.exists():
                with sqlite3.connect(backup) as dest:con.backup(dest)
        columns={r['name'] for r in con.execute('PRAGMA table_info(pages)')}
        with con:
            for name,kind in [('pdf_page','INTEGER'),('book_page','INTEGER'),('chapter','TEXT'),('section','TEXT'),('image_path','TEXT'),('thumb_path','TEXT')]:
                if name not in columns:con.execute(f'ALTER TABLE pages ADD COLUMN {name} {kind}')
        con.executescript(DDL)
        with con:
            for row in con.execute('SELECT document_id,number,metadata FROM base_package_pages').fetchall():
                data=json.loads(row['metadata'])
                text=(PRIVATE/'base-package'/f'text/p{row["number"]:03}.txt').read_text(encoding='utf-8')
                con.execute('UPDATE pages SET pdf_page=number,book_page=?,chapter=?,section=?,text=?,image_path=?,thumb_path=? WHERE document_id=? AND number=?',
                            (data['book_page'],data['chapter'],data['section'],text,data['image'],data['thumbnail'],row['document_id'],row['number']))
            for row in con.execute('SELECT document_id,outline FROM base_package_toc').fetchall():
                for entry in json.loads(row['outline']):
                    con.execute('INSERT OR REPLACE INTO toc VALUES(?,?,?,?,?,?,?)',(row['document_id'],entry['id'],entry['title'],entry['level'],entry['pdf_page'],entry['pdf_end'],entry['book_page']))
            con.execute('DELETE FROM pages_fts')
            con.execute('INSERT INTO pages_fts SELECT id,text,chapter,section FROM pages')
            con.execute('INSERT OR IGNORE INTO structured_migrations VALUES(1,?)',(datetime.now(timezone.utc).isoformat(),))

def digest(text):return hashlib.sha256(text.encode()).hexdigest()

def select_pages(con,pages=None,chapter=None):
    rows=con.execute('SELECT * FROM pages WHERE pdf_page IS NOT NULL ORDER BY document_id,pdf_page').fetchall()
    numbers=None
    if pages:
        numbers=set()
        for part in pages.split(','):
            ends=part.split('-');numbers.update(range(int(ends[0]),int(ends[-1])+1))
    return [r for r in rows if (numbers is None or r['pdf_page'] in numbers) and (not chapter or chapter.lower() in ((r['chapter'] or '')+' '+(r['section'] or '')).lower())]
