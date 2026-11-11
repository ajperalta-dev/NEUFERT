import io
import json
import math
import os
import textwrap
import uuid
from contextlib import closing
from pathlib import Path
from urllib.parse import urlparse
import fitz
from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, ConfigDict
from .storage import connect, private_dir, decode, MODEL
from .search import search

app=FastAPI(title='Neufert Digital — local API')

def database():
    with closing(connect()) as db:
        yield db

@app.middleware('http')
async def protect_writes(request:Request,call_next):
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin')
        allowed=os.environ.get('NEUFERT_APP_ORIGIN','http://localhost:3000').rstrip('/')
        if origin and origin.rstrip('/') not in (allowed,'http://127.0.0.1:3000'):
            return Response('Origin not permitted',status_code=403)
    return await call_next(request)

@app.get('/api/status')
def status(db=Depends(database)):
    documents=[dict(r) for r in db.execute('SELECT id,page_count,metadata FROM documents')]
    for doc in documents:
        doc['metadata']=json.loads(doc['metadata'])
        doc['processed_pages']=db.execute('SELECT COUNT(*) FROM pages WHERE document_id=?',(doc['id'],)).fetchone()[0]
    return {'documents':documents,'entries':db.execute('SELECT COUNT(*) FROM entries').fetchone()[0],
            'vectors':db.execute('SELECT COUNT(*) FROM vector_metadata WHERE model=?',(MODEL,)).fetchone()[0],
            'review':db.execute('SELECT COUNT(*) FROM entries WHERE needs_review=1').fetchone()[0],
            'llm_available':bool(os.environ.get('OPENAI_API_KEY') or os.environ.get('ANTHROPIC_API_KEY'))}

@app.get('/api/search')
def find(q:str=Query('',max_length=1000), typology:str|None=None,space:str|None=None,
         activity:str|None=None,equipment:str|None=None, min_cm:float|None=Query(None,ge=0),
         max_cm:float|None=Query(None,ge=0),review:bool=False,natural:bool=False,
         limit:int=Query(30,ge=1,le=100),offset:int=Query(0,ge=0),db=Depends(database)):
    if any(v is not None and not math.isfinite(v) for v in (min_cm,max_cm)):
        raise HTTPException(422,'Range must be finite')
    if min_cm is not None and max_cm is not None and min_cm > max_cm:
        raise HTTPException(422,'Invalid dimension range')
    return search(db,q,dict(typology=typology,space=space,activity=activity,equipment=equipment,
                           min_cm=min_cm,max_cm=max_cm,review=review),limit,offset,natural)

@app.get('/api/entries/{entry_id}')
def entry(entry_id:str,db=Depends(database)):
    row=db.execute('SELECT * FROM entries WHERE id=?',(entry_id,)).fetchone()
    if not row:
        raise HTTPException(404,'Entry not found')
    return decode(row)

class Reviewed(BaseModel):
    reviewed:bool

@app.patch('/api/entries/{entry_id}/review')
def review_entry(entry_id:str,body:Reviewed,db=Depends(database)):
    with db:
        result=db.execute('UPDATE entries SET reviewed=?,needs_review=? WHERE id=?',
                          (int(body.reviewed),int(not body.reviewed),entry_id))
    if not result.rowcount:
        raise HTTPException(404,'Entry not found')
    return {'ok':True}

@app.get('/api/documents/{doc_id}/pages/{number}')
def page(doc_id:str,number:int,db=Depends(database)):
    row=db.execute('SELECT * FROM pages WHERE document_id=? AND number=?',(doc_id,number)).fetchone()
    if not row:
        raise HTTPException(404,'Page not ingested')
    result=dict(row)
    for field in ('blocks','tables_json'):
        result[field]=json.loads(result[field])
    result['page_count']=db.execute('SELECT page_count FROM documents WHERE id=?',(doc_id,)).fetchone()[0]
    return result

@app.get('/api/documents/{doc_id}/source')
def source(doc_id:str,db=Depends(database)):
    row=db.execute('SELECT filename FROM documents WHERE id=?',(doc_id,)).fetchone()
    if not row or not Path(row[0]).is_file():
        raise HTTPException(404,'Source PDF unavailable')
    return FileResponse(row[0],media_type='application/pdf',filename='neufert.pdf',content_disposition_type='inline')

@app.get('/api/assets/{relative:path}')
def asset(relative:str):
    root=(private_dir()/'documents').resolve()
    path=(private_dir()/relative).resolve()
    if not path.is_relative_to(root) or path.suffix != '.webp' or not path.is_file():
        raise HTTPException(404,'Asset not found')
    return FileResponse(path,media_type='image/webp')

@app.get('/api/index')
def index(db=Depends(database)):
    return [dict(r) for r in db.execute('SELECT typology,COUNT(*) AS count FROM entries GROUP BY typology ORDER BY typology')]

@app.get('/api/favorites')
def favorites(db=Depends(database)):
    return [decode(r) for r in db.execute('SELECT e.* FROM entries e JOIN favorites f ON e.id=f.entry_id ORDER BY e.page_pdf')]

class Favorite(BaseModel):
    favorite:bool

@app.put('/api/favorites/{entry_id}')
def favorite(entry_id:str,body:Favorite,db=Depends(database)):
    if not db.execute('SELECT 1 FROM entries WHERE id=?',(entry_id,)).fetchone():
        raise HTTPException(404,'Entry not found')
    with db:
        if body.favorite:
            db.execute('INSERT OR IGNORE INTO favorites VALUES (?)',(entry_id,))
        else:
            db.execute('DELETE FROM favorites WHERE entry_id=?',(entry_id,))
    return {'ok':True}

class CollectionName(BaseModel):
    name:str=Field(min_length=1,max_length=120)

@app.get('/api/collections')
def collections(db=Depends(database)):
    return [dict(r) for r in db.execute('SELECT c.*,COUNT(ce.entry_id) AS count FROM collections c LEFT JOIN collection_entries ce ON c.id=ce.collection_id GROUP BY c.id ORDER BY c.created_at,c.id')]

@app.post('/api/collections',status_code=201)
def create_collection(body:CollectionName,db=Depends(database)):
    if not body.name.strip():
        raise HTTPException(422,'Empty name')
    collection_id=uuid.uuid4().hex
    with db:
        db.execute('INSERT INTO collections(id,name) VALUES (?,?)',(collection_id,body.name.strip()))
    return {'id':collection_id,'name':body.name.strip(),'count':0}

def collection_rows(db,collection_id):
    collection=db.execute('SELECT * FROM collections WHERE id=?',(collection_id,)).fetchone()
    if not collection:
        raise HTTPException(404,'Collection not found')
    rows=[decode(r) for r in db.execute('SELECT e.* FROM entries e JOIN collection_entries ce ON e.id=ce.entry_id WHERE ce.collection_id=? ORDER BY e.document_id,e.page_pdf,e.id',(collection_id,))]
    return dict(collection),rows

@app.get('/api/collections/{collection_id}')
def collection(collection_id:str,db=Depends(database)):
    item,rows=collection_rows(db,collection_id)
    return {**item,'entries':rows}

@app.delete('/api/collections/{collection_id}')
def delete_collection(collection_id:str,db=Depends(database)):
    collection_rows(db,collection_id)
    with db:
        db.execute('DELETE FROM collections WHERE id=?',(collection_id,))
    return {'ok':True}

@app.put('/api/collections/{collection_id}/entries/{entry_id}')
def add_to_collection(collection_id:str,entry_id:str,db=Depends(database)):
    collection_rows(db,collection_id)
    if not db.execute('SELECT 1 FROM entries WHERE id=?',(entry_id,)).fetchone():
        raise HTTPException(404,'Entry not found')
    with db:
        db.execute('INSERT OR IGNORE INTO collection_entries VALUES (?,?)',(collection_id,entry_id))
    return {'ok':True}

@app.delete('/api/collections/{collection_id}/entries/{entry_id}')
def remove_from_collection(collection_id:str,entry_id:str,db=Depends(database)):
    collection_rows(db,collection_id)
    with db:
        db.execute('DELETE FROM collection_entries WHERE collection_id=? AND entry_id=?',(collection_id,entry_id))
    return {'ok':True}

def export_text(name,entries):
    lines=[name,'']
    for item in entries:
        lines.extend([item['title_de'],f"PDF p. {item['page_pdf']} | printed: {item['page_printed'] or 'unknown'} | document: {item['document_id']}",
                      f"Extraction confidence: {item['confidence']:.0%}; review: {bool(item['needs_review'])}",item['text'],''])
        for d in item['dimensions']:
            lines.append(f"{d['valor']} {d['unidad']} — {d['contexto']}")
        lines.append('')
    return lines

@app.get('/api/collections/{collection_id}/export')
def export(collection_id:str,format:str=Query('markdown',pattern='^(markdown|pdf)$'),db=Depends(database)):
    collection,entries=collection_rows(db,collection_id)
    lines=export_text(collection['name'],entries)
    if format == 'markdown':
        # Escape raw HTML from source documents; Markdown remains plain extractive text.
        content='\n\n'.join(line.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;') for line in lines)
        return Response(content,media_type='text/markdown; charset=utf-8',headers={'Content-Disposition':'attachment; filename="neufert-collection.md"'})
    text='\n'.join(lines)
    # PyMuPDF Story paginates HTML and embeds fallback fonts automatically.
    import html
    story=fitz.Story('<html><body>'+''.join('<p>'+html.escape(line)+'</p>' for line in lines)+'</body></html>')
    stream=io.BytesIO()
    writer=fitz.DocumentWriter(stream)
    more=True
    while more:
        device=writer.begin_page(fitz.Rect(0,0,595,842))
        more,_=story.place(fitz.Rect(40,40,555,802))
        story.draw(device)
        writer.end_page()
    writer.close()
    return Response(stream.getvalue(),media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="neufert-collection.pdf"'})

@app.get('/api/documents/{doc_id}/toc')
def toc(doc_id:str,db=Depends(database)):
    if not db.execute('SELECT 1 FROM documents WHERE id=?',(doc_id,)).fetchone():
        raise HTTPException(404,'Document not found')
    report=private_dir()/'documents'/doc_id/'analysis.json'
    if not report.is_file():
        return []
    return json.loads(report.read_text()).get('toc',[])
