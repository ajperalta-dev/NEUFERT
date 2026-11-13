import logging
import numpy as np
from .config import MODEL
from .db import connect, initialize

_model=None
def model():
    global _model
    if _model is None:
        import torch
        torch.set_num_threads(2)
        from sentence_transformers import SentenceTransformer
        try:
            _model=SentenceTransformer(MODEL,local_files_only=True)
        except OSError:
            _model=SentenceTransformer(MODEL)
        _model.max_seq_length=512
    return _model

def build():
    initialize()
    with connect(vectors=True) as con:
        rows=con.execute('SELECT id,title,text FROM entries').fetchall()
        for n,r in enumerate(rows):
            words=(r['title']+' '+r['text']).split()
            chunks=[' '.join(words[i:i+180]) for i in range(0,max(1,len(words)),150)]
            missing=[(i,chunk) for i,chunk in enumerate(chunks) if not con.execute('SELECT 1 FROM embedding_chunks WHERE entry_id=? AND chunk_index=? AND model=?',(r['id'],i,MODEL)).fetchone()]
            if not missing:continue
            encoded=model().encode(['passage: '+chunk for i,chunk in missing],normalize_embeddings=True,batch_size=8)
            for (i,chunk),embedding in zip(missing,encoded):
                vector=embedding.astype(np.float32).tobytes()
                with con:
                    cur=con.execute('INSERT INTO embedding_chunks(entry_id,chunk_index,model) VALUES(?,?,?)',(r['id'],i,MODEL))
                    con.execute('INSERT INTO vectors(rowid,embedding) VALUES(?,?)',(cur.lastrowid,vector))
            logging.warning('Embeddings %s/%s',n+1,len(rows))

def nearest(con, query):
    if not con.execute('SELECT 1 FROM embedding_chunks LIMIT 1').fetchone():return []
    vector=model().encode('query: '+query,normalize_embeddings=True).astype(np.float32).tobytes()
    rows=con.execute('SELECT c.entry_id FROM (SELECT rowid,distance FROM vectors WHERE embedding MATCH ? AND k=100 ORDER BY distance) v JOIN embedding_chunks c ON c.id=v.rowid',(vector,)).fetchall()
    return list(dict.fromkeys(r[0] for r in rows))

if __name__=='__main__':build()
