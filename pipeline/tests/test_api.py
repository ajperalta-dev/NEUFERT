import fitz
from fastapi.testclient import TestClient
from pipeline.api import app
from pipeline.ingest import ingest
from pipeline.storage import private_dir

def test_workflow_exports_and_boundary_checks(book):
    with TestClient(app) as client:
        status=client.get('/api/status').json()
        assert status['entries']>0
        results=client.get('/api/search',params={'q':'pasillo'}).json()
        entry=results['results'][0]
        assert client.get('/api/entries/'+entry['id']).json()['bbox']==entry['bbox']
        page=client.get(f"/api/documents/{entry['document_id']}/pages/1").json()
        assert page['number']==1 and page['page_count']==2
        assert client.get('/api/assets/'+page['image']).headers['content-type']=='image/webp'
        assert client.get('/api/assets/documents/../../../neufert.sqlite3').status_code==404
        assert client.get('/api/assets/documents/%2e%2e/%2e%2e/neufert.sqlite3').status_code==404
        assert client.get('/api/entries/notfound').status_code==404
        assert client.get('/api/search?min_cm=200&max_cm=50').status_code==422
        assert client.get('/api/search?min_cm=nan').status_code==422
        assert client.get('/api/search?limit=0').status_code==422
        collection=client.post('/api/collections',json={'name':'Vivienda ñ — Küche'}).json()
        url=f"/api/collections/{collection['id']}"
        assert client.put(url+'/entries/'+entry['id']).is_success
        assert client.put(url+'/entries/'+entry['id']).is_success
        assert len(client.get(url).json()['entries'])==1
        assert client.put('/api/favorites/'+entry['id'],json={'favorite':True}).is_success
        assert len(client.get('/api/favorites').json())==1
        assert client.patch('/api/entries/'+entry['id']+'/review',json={'reviewed':True}).is_success
        markdown=client.get(url+'/export?format=markdown')
        assert f"PDF p. {entry['page_pdf']}" in markdown.text and entry['text'] in markdown.text
        response=client.get(url+'/export?format=pdf')
        assert response.status_code==200 and response.content.startswith(b'%PDF')
        with fitz.open(stream=response.content,filetype='pdf') as pdf:
            extracted=''.join(p.get_text() for p in pdf)
            assert 'PDF p. 1' in extracted and 'Krankenhaus' in extracted
        assert client.post('/api/collections',json={'name':'intruder'},headers={'Origin':'https://evil.example'}).status_code==403
        assert client.delete(url+'/entries/'+entry['id']).is_success
        assert client.get(url).json()['entries']==[]
        assert client.delete(url).is_success
        assert client.get(url).status_code==404

def test_concurrent_request_scoped_sqlite_connections(book):
    from concurrent.futures import ThreadPoolExecutor
    with TestClient(app) as client:
        def request(number):
            response=client.post('/api/collections',json={'name':f'Concurrent {number}'})
            assert response.status_code==201
            assert client.get('/api/search?q=pasillo').status_code==200
            return response.json()['id']
        with ThreadPoolExecutor(max_workers=6) as workers:
            ids=list(workers.map(request,range(12)))
        assert len(set(ids))==12
        assert len(client.get('/api/collections').json())==12
