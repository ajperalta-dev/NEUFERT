import json
import numpy as np
import pytest
from pydantic import ValidationError
from pipeline.ficha_schema import Dimension
from pipeline import structured_db
from pipeline.db import connect
from pipeline.config import MODEL

def test_ficha_ranges_and_status():
    d=Dimension(label='clearance',value=1.2,value_max=1.8,unit='m',context='range',ocr_raw='1,20–1,80')
    assert d.status=='uncertain' and d.ocr_raw=='1,20–1,80'
    with pytest.raises(ValidationError):Dimension(**(d.model_dump()|{'value_max':.5}))
    with pytest.raises(ValidationError):Dimension(**(d.model_dump()|{'status':'guessed'}))

def test_validation_retry_counts_usage_without_discarding_raw():
    from pipeline.vision_fichas import validated
    class Provider:
        calls=0
        def generate(self,image,prompt):
            self.calls+=1
            if self.calls==2:assert 'failed validation' in prompt
            return {'label':'ratio','value':2,'value_max':1 if self.calls==1 else None,'unit':'ratio','context':'2:1 proportion','ocr_raw':'2:1'}, {'prompt_tokens':10,'completion_tokens':20}
    provider=Provider()
    dimension,usage=validated(provider,b'image','Read image',Dimension)
    assert dimension.ocr_raw=='2:1' and dimension.value_max is None
    assert usage=={'prompt_tokens':20,'completion_tokens':40}

def test_additive_migration_twice(tmp_path,monkeypatch):
    path=tmp_path/'fixture.sqlite';private=tmp_path/'private';private.mkdir()
    monkeypatch.setattr(structured_db,'PRIVATE',private)
    monkeypatch.setattr(structured_db,'connect',lambda **kw:connect(path,**kw))
    with connect(path,vectors=True) as con:
        con.executescript('CREATE TABLE pages(id TEXT PRIMARY KEY,document_id TEXT,number INTEGER,text TEXT); CREATE TABLE embedding_chunks(model TEXT); CREATE TABLE base_package_pages(document_id TEXT,number INTEGER,metadata TEXT); CREATE TABLE base_package_toc(document_id TEXT,outline TEXT); CREATE VIRTUAL TABLE vectors USING vec0(embedding float[384]);')
        con.execute('INSERT INTO embedding_chunks VALUES(?)',(MODEL,))
        v=np.zeros(384,dtype=np.float32);v[0]=1
        con.execute('INSERT INTO vectors(embedding) VALUES(?)',(v.tobytes(),))
    structured_db.migrate();structured_db.migrate()
    with connect(path) as con:
        assert con.execute('SELECT count(*) FROM structured_migrations').fetchone()[0]==1
        assert {'book_page','chapter','thumb_path'}<={r['name'] for r in con.execute('PRAGMA table_info(pages)')}
        with pytest.raises(Exception):con.execute('INSERT INTO embeddings(entidad,id_entidad,modelo,dimensiones,vector,source_hash) VALUES(?,?,?,?,?,?)',('page','p','different',384,bytes(1536),'hash'))

@pytest.mark.parametrize('query,document',[('hospital corridor','hospital corridor'),('escaleras para viviendas','residential stairs'),('human body proportions','human body proportions'),('Rollstuhl Bewegungsfläche','wheelchair accessibility')])
def test_hybrid_three_queries(query,document,tmp_path,monkeypatch):
    from pipeline import page_embeddings
    path=tmp_path/'search.sqlite'
    monkeypatch.setattr(page_embeddings,'connect',lambda **kw:connect(path,**kw))
    query_vector=np.zeros((1,384),dtype=np.float32);query_vector[0,0]=1
    monkeypatch.setattr(page_embeddings,'encode',lambda *args:query_vector)
    with connect(path,vectors=True) as con:
        con.executescript('CREATE TABLE pages(id TEXT,pdf_page INTEGER,book_page INTEGER,chapter TEXT,section TEXT,text TEXT,image_path TEXT);'+structured_db.DDL)
        con.execute('INSERT INTO pages VALUES(?,?,?,?,?,?,?)',('p',40,27,'BASICS','Relationships',document,'p040.webp'))
        con.execute('INSERT INTO pages_fts VALUES(?,?,?,?)',('p',document,'BASICS','Relationships'))
        con.execute('INSERT INTO embeddings VALUES(?,?,?,?,?,?,?)',(1,'page','p',MODEL,384,query_vector.tobytes(),'hash'))
        con.execute('INSERT INTO entity_vectors(rowid,embedding) VALUES(?,?)',(1,query_vector.tobytes()))
    result=page_embeddings.search(query)
    assert result[0]['pdf_page']==40 and result[0]['book_page']==27
    assert result[0]['score']>1/61
