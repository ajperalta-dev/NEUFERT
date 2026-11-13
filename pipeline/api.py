import json
import uuid
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from .config import PRIVATE
from .db import initialize,connect
from .search import search,detail
from .taxonomy import TERMS
from .base_package import decorate,metadata,matches

initialize()
app=FastAPI(title='Neufert Digital local API')

@app.middleware('http')
async def local_writes(request:Request,call_next):
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin')
        if origin and origin not in ('http://127.0.0.1:3000','http://localhost:3000'):
            return Response(status_code=403)
    return await call_next(request)

@app.get('/api/status')
def status():
    with connect() as con:
        docs=[dict(r) for r in con.execute('SELECT * FROM documents')]
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='base_package_toc'").fetchone():
            for doc in docs:
                row=con.execute('SELECT outline FROM base_package_toc WHERE document_id=?',(doc['id'],)).fetchone()
                if row:doc['outline']=row[0]
        return {'documents':docs,'pages':con.execute('SELECT count(*) FROM pages').fetchone()[0], 'entries':con.execute('SELECT count(*) FROM entries').fetchone()[0], 'vectors':con.execute('SELECT count(*) FROM embedding_chunks').fetchone()[0], 'taxonomy':TERMS}

@app.get('/api/v1/search')
def find(q:str='',typology:str='',space:str='',use:str='',furniture:str='',collection:str='',min:float|None=None,max:float|None=None,review:bool=False,offset:int=Query(0,ge=0),limit:int=Query(24,ge=1,le=100)):
    return search(q,{'typology':typology,'space':space,'use':use,'furniture':furniture,'min':min,'max':max,'review':review,'collection':collection},offset,limit)

@app.get('/api/search')
def hybrid_find(q:str=Query('',max_length=1000),chapter:str|None=None,result_type:str=Query('all',pattern='^(all|page|ficha)$'),include_uncertain:bool=True,limit:int=Query(24,ge=1,le=100)):
    from .hybrid_api import results
    return results(q,chapter,result_type,include_uncertain,limit)

@app.get('/api/page-search')
def find_pages(q:str=Query('',max_length=1000),chapter:str|None=None,limit:int=Query(10,ge=1,le=100)):
    from .page_embeddings import search as page_search
    return {'items':page_search(q,limit=limit,chapter=chapter)}

@app.get('/api/reports/structured-pilot')
def structured_pilot_report():
    path=PRIVATE/'reports/pilot-review.html'
    if not path.exists():path=PRIVATE/'reports/piloto.html'
    if not path.exists():raise HTTPException(404,'Pilot report is not ready')
    html=path.read_text(encoding='utf-8').replace('src="../base-package/','src="/api/assets/base-package/')
    return Response(html,media_type='text/html')

@app.get('/api/reports/structured-book')
def structured_book_report():
    path=PRIVATE/'reports/piloto.html'
    if not path.exists():raise HTTPException(404,'Book report is not ready')
    html=path.read_text(encoding='utf-8').replace('src="../base-package/','src="/api/assets/base-package/').replace('Pilot evidence: PDF 39â€“48','Full-book extraction progress')
    return Response(html,media_type='text/html')

@app.get('/api/reports/pass2')
def pass2_report():
    path=PRIVATE/'reports/segunda_pasada.html'
    if not path.exists():raise HTTPException(404,'Pilot is still running')
    return Response(path.read_text(encoding='utf-8').replace('src="../','src="/api/assets/'),media_type='text/html')

@app.get('/api/reports/pass2-comparison')
def pass2_comparison_report():
    path=PRIVATE/'pass2-runs/sol61-pilot-39-48/comparison.html'
    if not path.exists():raise HTTPException(404,'Comparison pilot is still running')
    markup=path.read_text(encoding='utf-8').replace('src="','src="/api/assets/pass2-runs/sol61-pilot-39-48/')
    return Response(markup,media_type='text/html')

@app.get('/api/reports/structured-progress')
def structured_progress():
    path=PRIVATE/'reports/full-book-progress.json'
    if not path.exists():raise HTTPException(404,'Book run has not started')
    return json.loads(path.read_text(encoding='utf-8'))

@app.get('/api/entries/{eid}')
def entry(eid:str):
    with connect() as con: item=detail(con,eid)
    if item is None:raise HTTPException(404)
    return item

@app.post('/api/entries/{eid}/review')
def reviewed(eid:str):
    with connect() as con:
        if not con.execute('SELECT 1 FROM entries WHERE id=?',(eid,)).fetchone():raise HTTPException(404)
        con.execute('UPDATE entries SET review=0 WHERE id=?',(eid,))
    return {'ok':True}

@app.get('/api/pages/{doc}/{number}')
def page(doc:str,number:int):
    with connect() as con:
        r=con.execute('SELECT * FROM pages WHERE document_id=? AND number=?',(doc,number)).fetchone()
        if not r:raise HTTPException(404,'Page not yet ingested')
        return decorate(con,dict(r))

@app.get('/api/pages/{doc}/{number}/words')
def page_words(doc:str,number:int,q:str=Query('',max_length=1000)):
    with connect() as con:
        if not metadata(con,doc,number):raise HTTPException(404,'No prepared word coordinates for this page')
    return matches(number,q)

@app.get('/api/assets/{asset:path}')
def asset(asset:str):
    path=(PRIVATE/asset).resolve()
    if not path.is_relative_to(PRIVATE.resolve()) or path.suffix not in ('.webp','.png') or not path.is_file():raise HTTPException(404)
    return FileResponse(path,media_type='image/png' if path.suffix=='.png' else 'image/webp')

class Collection(BaseModel):
    name:str=Field(min_length=1,max_length=120)

@app.get('/api/collections')
def collections():
    with connect() as con:
        return [dict(r)|{'entries':[x[0] for x in con.execute('SELECT entry_id FROM collection_entries WHERE collection_id=?',(r['id'],))]} for r in con.execute('SELECT * FROM collections ORDER BY created')]

@app.post('/api/collections')
def create(body:Collection):
    cid=uuid.uuid4().hex
    with connect() as con:con.execute('INSERT INTO collections(id,name) VALUES(?,?)',(cid,body.name.strip()))
    return {'id':cid}

@app.put('/api/collections/{cid}/{eid}')
def add(cid:str,eid:str):
    with connect() as con:
        if not con.execute('SELECT 1 FROM collections WHERE id=?',(cid,)).fetchone() or not con.execute('SELECT 1 FROM entries WHERE id=?',(eid,)).fetchone():raise HTTPException(404)
        con.execute('INSERT OR IGNORE INTO collection_entries VALUES(?,?)',(cid,eid))
    return {'ok':True}

@app.delete('/api/collections/{cid}/{eid}')
def remove(cid:str,eid:str):
    with connect() as con:con.execute('DELETE FROM collection_entries WHERE collection_id=? AND entry_id=?',(cid,eid))
    return {'ok':True}

@app.get('/api/export/{cid}')
def export(cid:str):
    with connect() as con:
        c=con.execute('SELECT * FROM collections WHERE id=?',(cid,)).fetchone()
        if not c:raise HTTPException(404)
        items=[detail(con,r[0]) for r in con.execute('SELECT entry_id FROM collection_entries WHERE collection_id=?',(cid,))]
    text='# '+c['name']+'\n\n'
    for item in items:
        text+=f"## {item['title']}\n\nPDF p. {item['pagina_pdf']} / impresa {item['pagina_impresa'] or 'â€”'}\n\n{item['text']}\n\n"
    return Response(text,media_type='text/markdown',headers={'Content-Disposition':'attachment; filename="neufert-collection.md"'})

class NaturalQuery(BaseModel):
    query:str=Field(min_length=1,max_length=1000)

@app.post('/api/ask')
def ask(body:NaturalQuery):
    from . import llm
    query,filters=body.query,{}
    warning=None
    if llm.available():
        try:query,filters=llm.plan(body.query)
        except Exception:warning='LLM unavailable; local search used.'
    result=search(query,filters,limit=24)
    result['evidence']=[]
    if llm.available() and result['items']:
        try:result['evidence']=llm.evidence(body.query,result['items'])
        except Exception:warning='LLM unavailable; retrieved pages retained.'
    result.update({'reformulated':query,'structured_filters':filters,'warning':warning})
    return result
