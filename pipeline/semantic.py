"""Explicit model download; request serving uses the local cache only."""
import argparse
import os
from functools import lru_cache
import numpy as np
from .storage import connect, MODEL, private_dir

@lru_cache(maxsize=1)
def model(download=False):
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(MODEL,cache_folder=str(private_dir()/'models'),
                               local_files_only=not download,device='cpu')

def vector(text, query=False):
    result = model().encode(('query: ' if query else 'passage: ') + text,
                            normalize_embeddings=True)
    return np.asarray(result,dtype=np.float32).tobytes()

def build(download=False):
    encoder = model(download)
    db = connect()
    try:
        rows = db.execute('SELECT id,title_de,text FROM entries WHERE id NOT IN (SELECT entry_id FROM vector_metadata WHERE model=?)',(MODEL,)).fetchall()
        for offset in range(0,len(rows),16):
            batch = rows[offset:offset+16]
            embeddings = encoder.encode(['passage: '+r['title_de']+'\n'+r['text'] for r in batch],normalize_embeddings=True)
            with db:
                for row,embedding in zip(batch,embeddings):
                    db.execute('DELETE FROM entry_vectors WHERE entry_id=?',(row['id'],))
                    db.execute('INSERT INTO entry_vectors(entry_id,embedding) VALUES (?,?)',
                               (row['id'],np.asarray(embedding,dtype=np.float32).tobytes()))
                    db.execute('INSERT OR REPLACE INTO vector_metadata VALUES (?,?)',(row['id'],MODEL))
            print(f'Embedded {min(offset+16,len(rows))}/{len(rows)}',flush=True)
    finally:
        db.close()

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--download',action='store_true')
    build(parser.parse_args().download)
