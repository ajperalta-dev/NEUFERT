import numpy as np
from pipeline.search import search
from pipeline.storage import MODEL

def test_fts_multilingual_and_injection_safe(db):
    for query in ['Krankenhaus','pasillo','corridor']:
        result=search(db,query)
        assert result['results'] and result['results'][0]['page_pdf']==1
        assert result['mode']=='fts5'
    for query in ['escaleras viviendas','stairs housing','Treppen Wohnhaus']:
        assert search(db,query)['results'][0]['page_pdf']==2
    assert search(db,'xyzdoesnotexist')['total']==0
    search(db,'" OR 1=1; DROP TABLE entries; --')
    assert db.execute('SELECT COUNT(*) FROM entries').fetchone()[0]>0

def test_filters_dimension_units_and_facets(db):
    result=search(db,'',{'typology':'salud','min_cm':200,'max_cm':250})
    assert result['total']>=1
    assert all(i['page_pdf']==1 for i in result['results'])
    assert 'salud' in result['facets']['typology']
    result=search(db,'',{'min_cm':85,'max_cm':95})
    assert result['results'] and all(i['page_pdf']==2 for i in result['results'])
    assert search(db,'',{'space':'garaje'})['total']==0
    assert search(db,'',limit=1,offset=1)['results']

def test_hybrid_rrf_and_filters(db,monkeypatch):
    import pipeline.semantic as semantic
    entries=db.execute('SELECT id,page_pdf FROM entries').fetchall()
    for entry in entries:
        vector=np.zeros(384,dtype=np.float32);vector[0 if entry['page_pdf']==1 else 1]=1
        with db:
            db.execute('INSERT INTO entry_vectors VALUES (?,?)',(entry['id'],vector.tobytes()))
            db.execute('INSERT INTO vector_metadata VALUES (?,?)',(entry['id'],MODEL))
    query=np.zeros(384,dtype=np.float32);query[0]=1
    monkeypatch.setattr(semantic,'vector',lambda text,query=False:np.array([1]+[0]*383,dtype=np.float32).tobytes())
    result=search(db,'pasillo')
    assert result['mode']=='hybrid' and result['results'][0]['page_pdf']==1
    result=search(db,'pasillo',{'typology':'vivienda'})
    assert result['results'] and all(i['typology']=='vivienda' for i in result['results'])

def test_missing_model_and_llm_are_honest_fallbacks(db,monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False);monkeypatch.delenv('ANTHROPIC_API_KEY',raising=False)
    result=search(db,'pasillo',natural=True)
    assert result['mode']=='fts5' and result['interpretation'] is None
    assert 'semantic_index_missing' in result['warnings']


def test_llm_interpretation_is_used_without_generated_facts(db,monkeypatch):
    import pipeline.search as module
    monkeypatch.setattr(module,'interpret',lambda q:({'query_de':'Krankenhaus Flur','typology':'salud'},None))
    result=search(db,'hospital circulation',natural=True)
    assert result['results'][0]['page_pdf']==1
    assert result['filters']['typology']=='salud'
    assert result['interpretation']['query_de']=='Krankenhaus Flur'
    assert 'summary' not in result
