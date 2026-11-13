from fastapi.testclient import TestClient
from pipeline.api import app

def test_private_asset_traversal_and_unknown_entry():
    client=TestClient(app)
    assert client.get('/api/assets/%2E%2E/neufert.sqlite3').status_code==404
    assert client.get('/api/entries/missing').status_code==404

def test_collection_create_and_origin_guard():
    client=TestClient(app)
    assert client.post('/api/collections',json={'name':'x'},headers={'Origin':'https://example.com'}).status_code==403

def test_query_fallback_without_llm(monkeypatch):
    from pipeline import llm
    monkeypatch.setattr(llm,'available',lambda:False)
    import pipeline.api as api
    monkeypatch.setattr(api,'search',lambda *args,**kw:{'items':[],'total':0,'facets':{}})
    response=TestClient(app).post('/api/ask',json={'query':'escaleras para viviendas'})
    assert response.status_code==200
    assert response.json()['reformulated']=='escaleras para viviendas'
