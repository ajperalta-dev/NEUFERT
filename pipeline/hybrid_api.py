import json,re
from .config import PRIVATE
from .db import connect
from .page_embeddings import search

def label(d):
    if d['status']=='uncertain':return 'Incierto'
    if d['status']=='corrected':return 'Corregido'
    if d['status']=='number_confirmed_unit_pending':return 'Número confirmado, unidad pendiente'
    if d['status']=='verified_unit_inferred':return 'Unidad inferida del contexto de la página'
    return 'Verificado por IA (2 pasadas)' if d.get('verification_level')=='two_pass' else 'Verificado por IA'

def results(q='',chapter=None,result_type='all',include_uncertain=True,limit=24):
    pages=search(q,limit=100,chapter=chapter) if q.strip() else []
    items=[]
    with connect() as c:
        has_v2=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='verification_pass2_units_v2'").fetchone()
        v2={}
        if has_v2:
            for row in c.execute("SELECT id,payload FROM verification_pass2_units_v2 WHERE run_id='luna-unit-context-v2-full'"):
                v2[row['id']]=json.loads(row['payload'])
        if not q.strip():pages=[dict(r) for r in c.execute('SELECT * FROM pages WHERE (? IS NULL OR chapter=?) ORDER BY pdf_page LIMIT 100',(chapter,chapter))]
        for p in pages:
            base={k:p.get(k) for k in ('pdf_page','book_page','chapter','section')}
            snippet=p.get('snippet',p.get('text','')[:300])
            tokens=re.findall(r'\w+',q)
            marked=re.sub('('+'|'.join(map(re.escape,tokens))+')',r'[[\1]]',snippet,flags=re.I) if tokens else snippet
            words_path=PRIVATE/'base-package/words'/f"p{p['pdf_page']:03}.json"
            words=json.loads(words_path.read_text(encoding='utf-8'))['words'] if words_path.exists() else []
            if result_type!='ficha':items.append(dict(base,type='page',id=p['id'],ficha_id=None,title=p.get('section') or 'Page '+str(p['pdf_page']),snippet=marked,dimensions=[]))
            if result_type!='page':
                for row in c.execute('SELECT payload FROM fichas WHERE page_id=?',(p['id'],)):
                    f=json.loads(row[0]);ds=[]
                    for i,d in enumerate(f['dimensions']):
                        check=v2.get(f"{f['id']}:{i}")
                        if check:
                            d=dict(d,status=check['status_after'],verification_level=check.get('verification_level'))
                            if check.get('unit_source'):
                                d.update(unit=check.get('unit_after',''),unit_source=check.get('unit_source'),
                                         unit_citation=check.get('unit_citation'),unit_bbox=check.get('unit_bbox'),
                                         unit_page_pdf=check.get('unit_page_pdf'))
                            elif check['status_after']=='number_confirmed_unit_pending':
                                d['unit']=''
                            d['verification_pass2_unit_context_v2']=check
                        if not include_uncertain and d['status'] in ('uncertain','number_confirmed_unit_pending'):continue
                        d=dict(d,id_cota=f"{f['id']}:{i}",status_label=label(d));d['reason']=(d.get('verification_pass2') or {}).get('reason','No confirmado con claridad en la primera pasada' if d['status']=='uncertain' else '')
                        if check:
                            d['reason']=check.get('reason') or d['reason']
                            d['unit_inference_reason']=check.get('unit_inference_reason')
                        from .verify_pass2 import locate
                        d['bbox']=(d.get('verification_pass2') or {}).get('bbox') or locate(words,d)[1]
                        ds.append(d)
                    items.append(dict(base,type='ficha',id=f['id'],ficha_id=f['id'],title=f['title'],snippet=marked,summary=f['summary'],dimensions=ds))
    return {'items':items[:limit],'total':len(items),'chapters':sorted({p.get('chapter') for p in pages if p.get('chapter')})}
