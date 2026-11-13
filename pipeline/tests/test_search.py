import json
from pipeline.db import connect,initialize
from pipeline.search import search

def test_fts_multilingual_filter_and_literal_query(tmp_path,monkeypatch):
    path=tmp_path/'test.sqlite'
    initialize(path)
    import pipeline.search as retrieval
    monkeypatch.setattr(retrieval,'connect',lambda **kw:connect(path,**kw))
    with connect(path) as con:
        con.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?)',('doc','fixture','en','test',1,'{}','[]'))
        con.execute('INSERT INTO pages VALUES(?,?,?,?,?,?,?,?,?,?,?)',('p','doc',1,'12',600,800,'Hospital corridor','[]','[]','page.webp','test'))
        con.execute('INSERT INTO entries VALUES(?,?,?,?,?,?,?,?,?,?,?)',('e','p','Hospital corridors',None,None,'Hospital corridors','Minimum width 2.4 m','[0,0,600,800]',.5,1,'Hospitals'))
        con.execute('INSERT INTO entries_fts VALUES(?,?,?,?)',('e','Hospital corridors','Minimum width 2.4 m','salud pasillo'))
        con.execute('INSERT INTO tags VALUES(?,?,?)',('e','typology','salud'))
        con.execute('INSERT INTO dimensions(entry_id,name,value,unit,context,metres) VALUES(?,?,?,?,?,?)',('e','width',2.4,'m','width 2.4 m',2.4))
    result=search('pasillo de hospital',semantic=False)
    assert result['total']==1
    assert result['items'][0]['pagina_pdf']==1
    assert result['facets']['typology']['salud']==1
    assert search('hospital',{'typology':'vivienda'},semantic=False)['total']==0
    assert search('hospital',{'min':3},semantic=False)['total']==0
    assert search('" OR * --',semantic=False)['total']==0
