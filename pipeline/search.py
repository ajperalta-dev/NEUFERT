import json
import re
from collections import Counter
from .db import connect
from .taxonomy import expand_query
from .base_package import decorate

def detail(con, eid):
    row=con.execute('SELECT e.*,p.number pagina_pdf,p.printed pagina_impresa,p.image,p.width,p.height,p.document_id FROM entries e JOIN pages p ON e.page_id=p.id WHERE e.id=?',(eid,)).fetchone()
    if not row:return None
    item=dict(row);item['bbox']=json.loads(item['bbox'])
    item['figures']=[dict(r) for r in con.execute('SELECT * FROM figures WHERE entry_id=?',(eid,))]
    def figure_area(figure):
        box=json.loads(figure['bbox'])
        return (box[2]-box[0])*(box[3]-box[1])
    item['figures'].sort(key=figure_area,reverse=True)
    item['dimensions']=[dict(r) for r in con.execute('SELECT * FROM dimensions WHERE entry_id=?',(eid,))]
    item['tags']=[dict(r) for r in con.execute('SELECT kind,value FROM tags WHERE entry_id=?',(eid,))]
    return decorate(con,item)

def search(query='', filters=None, offset=0, limit=24, semantic=True):
    filters=filters or {}
    with connect(vectors=True) as con:
        scores={}; snippets={}
        if query.strip():
            terms=expand_query(query)
            expression=' OR '.join('"'+t.replace('"','')+'"' for t in terms)
            lexical=con.execute("SELECT id,snippet(entries_fts,2,'[[',']]',' … ',35) snippet FROM entries_fts WHERE entries_fts MATCH ? ORDER BY bm25(entries_fts,0,6,1,2)",(expression,)).fetchall() if expression else []
            for i,r in enumerate(lexical):scores[r['id']]=1/(60+i+1);snippets[r['id']]=r['snippet']
            if semantic:
                from .vectors import nearest
                for i,eid in enumerate(nearest(con,query)):
                    scores[eid]=scores.get(eid,0)+1/(60+i+1)
            ids=sorted(scores,key=lambda eid:-scores[eid])
        else:
            ids=[r[0] for r in con.execute('SELECT e.id FROM entries e JOIN pages p ON p.id=e.page_id ORDER BY p.number')]
        items=[detail(con,eid) for eid in ids]
        # Front matter is accessible in the viewer/index but does not outrank
        # actual building references in this identified edition.
        excluded_docs={r[0] for r in con.execute("SELECT id FROM documents WHERE edition LIKE '4th English edition%'")}
        items=[i for i in items if i['document_id'] not in excluded_docs or 14<=i['pagina_pdf']<=587]
        def accepts(item,ignore=None):
            if filters.get('collection'):
                if not con.execute('SELECT 1 FROM collection_entries WHERE collection_id=? AND entry_id=?',(filters['collection'],item['id'])).fetchone():return False
            for kind in ('typology','space','use','furniture'):
                if kind!=ignore and filters.get(kind) and not any(t['kind']==kind and t['value'] in filters[kind].split(',') for t in item['tags']):return False
            if filters.get('review') and not item['review']:return False
            low,high=filters.get('min') or None,filters.get('max') or None
            if low is not None or high is not None:
                if not any(d['metres'] is not None and (low is None or d['metres']>=float(low)) and (high is None or d['metres']<=float(high)) for d in item['dimensions']):return False
            return True
        facets={kind:dict(Counter(t['value'] for item in items if accepts(item,kind) for t in item['tags'] if t['kind']==kind)) for kind in ('typology','space','use','furniture')}
        matched=[item for item in items if accepts(item)]
        for item in matched:item['snippet']=snippets.get(item['id'],item['text'][:240])
        return {'items':matched[offset:offset+limit],'total':len(matched),'facets':facets}
