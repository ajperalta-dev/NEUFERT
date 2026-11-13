import numpy as np
from pipeline.db import connect, initialize
from pipeline import vectors

def test_local_vector_nearest_keeps_entry_identity(tmp_path,monkeypatch):
    path=tmp_path/'vectors.sqlite'
    initialize(path)
    query=np.zeros(384,dtype=np.float32);query[0]=1
    other=np.zeros(384,dtype=np.float32);other[1]=1
    class Encoder:
        def encode(self,*args,**kwargs):return query
    monkeypatch.setattr(vectors,'model',lambda:Encoder())
    with connect(path,vectors=True) as con:
        con.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?)',('d','fixture','en','fixture',1,'{}','[]'))
        con.execute('INSERT INTO pages VALUES(?,?,?,?,?,?,?,?,?,?,?)',('p','d',1,'1',600,800,'fixture','[]','[]','page.webp','test'))
        for eid,embedding in [('relevant',query),('other',other)]:
            con.execute('INSERT INTO entries VALUES(?,?,?,?,?,?,?,?,?,?,?)',(eid,'p',eid,None,None,None,'fixture','[0,0,1,1]',1,0,'fixture'))
            cur=con.execute('INSERT INTO embedding_chunks(entry_id,chunk_index,model) VALUES(?,?,?)',(eid,0,vectors.MODEL))
            con.execute('INSERT INTO vectors(rowid,embedding) VALUES(?,?)',(cur.lastrowid,embedding.tobytes()))
        assert vectors.nearest(con,'consulta multilingüe')==['relevant','other']
