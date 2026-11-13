import logging
import os
import time
import re
import httpx
import numpy as np
from .config import MODEL
from .db import connect
from .structured_db import contract,digest
from .vectors import model
from .taxonomy import expand_query,match_terms,TERMS,normalize

def retry(fn):
    for attempt in range(4):
        try:return fn()
        except (httpx.TimeoutException,httpx.NetworkError,httpx.HTTPStatusError) as error:
            if isinstance(error,httpx.HTTPStatusError) and error.response.status_code not in (408,429,500,502,503,504):raise
            if attempt==3:raise
            time.sleep(2**attempt)

def encode(texts,prefix):
    provider=os.getenv('NEUFERT_EMBEDDING_PROVIDER','local')
    if os.getenv('NEUFERT_EMBEDDING_MODEL',MODEL)!=MODEL:raise ValueError('Embedding model changes are forbidden')
    inputs=[prefix+text for text in texts]
    if provider=='local':values=model().encode(inputs,normalize_embeddings=True,batch_size=8,show_progress_bar=False)
    elif provider=='compatible':
        url=os.environ['NEUFERT_EMBEDDING_URL'].rstrip('/')+'/embeddings'
        key=os.getenv('NEUFERT_EMBEDDING_API_KEY','')
        def call():
            r=httpx.post(url,headers={'Authorization':'Bearer '+key} if key else {},json={'model':MODEL,'input':inputs},timeout=120);r.raise_for_status()
            data=r.json()
            if data.get('model')!=MODEL:raise ValueError('Provider returned a different model')
            return [x['embedding'] for x in sorted(data['data'],key=lambda x:x['index'])]
        values=retry(call)
    else:raise ValueError('Embedding provider must be local or compatible')
    vectors=np.asarray(values,dtype=np.float32)
    if vectors.shape!=(len(texts),384) or not np.isfinite(vectors).all():raise ValueError('Invalid embedding dimensions or values')
    norms=np.linalg.norm(vectors,axis=1,keepdims=True)
    if (norms==0).any():raise ValueError('Zero embedding')
    return vectors/norms

def build(rows,batch_size=8):
    with connect(vectors=True) as con:
        contract(con)
        pending=[]
        for entity,eid,text in rows:
            fingerprint=digest(text)
            old=con.execute('SELECT source_hash,modelo,dimensiones FROM embeddings WHERE entidad=? AND id_entidad=?',(entity,eid)).fetchone()
            if old and old['source_hash']==fingerprint and old['modelo']==MODEL and old['dimensiones']==384:continue
            pending.append((entity,eid,text,fingerprint))
        for start in range(0,len(pending),batch_size):
            group=pending[start:start+batch_size];texts=[];counts=[]
            for _,_,text,_ in group:
                words=text.split();chunks=[' '.join(words[i:i+180]) for i in range(0,max(1,len(words)),150)]
                counts.append(len(chunks));texts.extend(chunks)
            encoded=encode(texts,'passage: ');position=0
            with con:
                for (entity,eid,text,fingerprint),count in zip(group,counts):
                    vector=encoded[position:position+count].mean(axis=0);position+=count
                    vector=(vector/np.linalg.norm(vector)).astype(np.float32).tobytes()
                    con.execute('INSERT INTO embeddings(entidad,id_entidad,modelo,dimensiones,vector,source_hash) VALUES(?,?,?,?,?,?) ON CONFLICT(entidad,id_entidad) DO UPDATE SET vector=excluded.vector,source_hash=excluded.source_hash', (entity,eid,MODEL,384,vector,fingerprint))
                    rid=con.execute('SELECT rowid FROM embeddings WHERE entidad=? AND id_entidad=?',(entity,eid)).fetchone()[0]
                    con.execute('DELETE FROM entity_vectors WHERE rowid=?',(rid,));con.execute('INSERT INTO entity_vectors(rowid,embedding) VALUES(?,?)',(rid,vector))
            logging.info('Embedded %s/%s entities',min(start+batch_size,len(pending)),len(pending))

def search(query,limit=10,chapter=None,pages=None):
    tokens=re.findall(r'\w+',normalize(query))
    variants=' '.join([query]+[w[:-1] for w in tokens if w.endswith('s')]+[w[:-2] for w in tokens if w.endswith('es')])
    terms=expand_query(variants)
    if not terms:return []
    fallback=' OR '.join('"'+word+'"' for word in terms)
    concepts={}
    for kind,key in match_terms(variants):concepts.setdefault(kind,set()).update(re.findall(r'\w+',normalize(' '.join(TERMS[kind][key]))))
    expression=' AND '.join('('+' OR '.join('"'+t+'"' for t in sorted(group))+')' for group in concepts.values()) if concepts else fallback
    with connect(vectors=True) as con:
        lexical=con.execute('SELECT page_id FROM pages_fts WHERE pages_fts MATCH ? ORDER BY bm25(pages_fts,0,1,2,3)',(expression,)).fetchall()
        if not lexical and expression!=fallback:lexical=con.execute('SELECT page_id FROM pages_fts WHERE pages_fts MATCH ? ORDER BY bm25(pages_fts,0,1,2,3)',(fallback,)).fetchall()
        scores={r[0]:1/(61+i) for i,r in enumerate(lexical)}
        vector=encode([query],'query: ')[0].astype(np.float32).tobytes()
        neighbors=con.execute('SELECT e.entidad,e.id_entidad,v.distance FROM (SELECT rowid,distance FROM entity_vectors WHERE embedding MATCH ? AND k=100 ORDER BY distance) v JOIN embeddings e ON e.rowid=v.rowid ORDER BY v.distance',(vector,)).fetchall()
        seen_pages=set()
        for i,r in enumerate(neighbors):
            pid=r['id_entidad'] if r['entidad']=='page' else con.execute('SELECT page_id FROM fichas WHERE id=?',(r['id_entidad'],)).fetchone()[0]
            if pid not in seen_pages:scores[pid]=scores.get(pid,0)+1/(61+i)
            seen_pages.add(pid)
        result=[]
        allowed=None
        if chapter or pages:
            from .structured_db import select_pages
            allowed={p['id'] for p in select_pages(con,pages,chapter)}
        ordered=[pid for pid in sorted(scores,key=lambda p:-scores[p]) if allowed is None or pid in allowed]
        for pid in ordered[:limit]:
            row=dict(con.execute('SELECT id,pdf_page,book_page,chapter,section,text,image_path FROM pages WHERE id=?',(pid,)).fetchone())
            words=row.pop('text');tokens={w.lower() for w in terms}
            pos=next((i for i in range(len(words)) if any(words[i:i+len(t)].lower()==t for t in tokens)),0)
            row['snippet']=words[max(0,pos-80):pos+280];row['score']=scores[pid];result.append(row)
        return result
