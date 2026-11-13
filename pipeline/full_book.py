"""Chapter-by-chapter vision processing after explicit pilot approval."""
import json
import logging
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from .config import PRIVATE
from .db import connect
from .structured_db import digest
from .vision_fichas import run,report
from .page_embeddings import build
from .ocr_traceability import enforce,ficha_text

def reference_only(page):
    return page['pdf_page']<=13 or page['chapter'] in ('REFERENCES','INDEX') or page['pdf_page'] in (607,608)

def snapshot():
    with connect() as con:
        counts={r[0]:r[1] for r in con.execute('SELECT status,count(*) FROM vision_progress GROUP BY status')}
        chapters=[dict(r) for r in con.execute('SELECT p.chapter,p.section,count(*) total,sum(v.status=\'complete\') complete,sum(v.status=\'failed\') failed FROM pages p LEFT JOIN vision_progress v ON v.page_id=p.id GROUP BY p.chapter,p.section ORDER BY min(p.pdf_page)')]
    data={'updated':datetime.now(timezone.utc).isoformat(),'counts':counts,'chapters':chapters}
    target=PRIVATE/'reports/full-book-progress.json';target.parent.mkdir(exist_ok=True)
    temporary=target.with_suffix('.tmp');temporary.write_text(json.dumps(data,indent=2),encoding='utf-8');temporary.replace(target)
    return data

def process(page):
    for attempt in range(2):
        try:
            run([page],resume=True)
            return True
        except Exception as error:
            logging.exception('PDF %s attempt %s failed',page['pdf_page'],attempt+1)
            # Authentication/quota failures must not consume requests for more pages.
            status=getattr(getattr(error,'response',None),'status_code',None)
            if status in (401,403,429):raise
            if attempt==0:time.sleep(2)
            else:
                with connect() as con:
                    con.execute('INSERT OR REPLACE INTO vision_progress VALUES(?,?,?,?,?,?,?)',(page['id'],digest(page['text']),'gpt-6-luna','failed',0,0,datetime.now(timezone.utc).isoformat()))
                with (PRIVATE/'reports/full-book-failures.jsonl').open('a',encoding='utf-8') as stream:
                    stream.write(json.dumps({'pdf_page':page['pdf_page'],'error':str(error),'time':datetime.now(timezone.utc).isoformat()})+'\n')
    return False

def estimate(rows):
    with connect() as con:done={r[0] for r in con.execute("SELECT page_id FROM vision_progress WHERE status='complete'")}
    pending=[p for p in rows if not reference_only(p) and p['id'] not in done]
    records=[json.loads(line) for usage in PRIVATE.glob('vision-usage*.jsonl') for line in usage.read_text(encoding='utf-8').splitlines() if line.strip()]
    cost=sum((r.get('usage',{}).get('prompt_tokens',0)*.1+r.get('usage',{}).get('completion_tokens',0)*.5)/1000000 for r in records)
    return {'selected_pages':len(rows),'remaining_content_pages':len(pending),'reference_only_pages':sum(reference_only(p) for p in rows),
            'base_vision_calls':2*len(pending),'estimated_additional_usd_from_observed_usage':round(cost/max(1,len(done))*len(pending),4),
            'note':'Observed Luna standard-rate estimate; retries, image density and output size change actual usage.'}

def run_book(rows,workers=4):
    groups=OrderedDict()
    with connect() as con:
        done={r[0] for r in con.execute("SELECT page_id FROM vision_progress WHERE status='complete'")}
        for page in rows:
            if reference_only(page):
                con.execute('INSERT OR REPLACE INTO vision_progress VALUES(?,?,?,?,?,?,?)',(page['id'],digest(page['text']),'not-applicable','reference_only',0,0,datetime.now(timezone.utc).isoformat()))
            else:groups.setdefault((page['chapter'],page['section']),[]).append(page)
    snapshot()
    for (chapter,section),pages in groups.items():
        pending=[p for p in pages if p['id'] not in done]
        logging.info('CHAPTER %s / %s: %s pending, %s retained',chapter,section,len(pending),len(pages)-len(pending))
        if pending:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures={pool.submit(process,page):page for page in pending}
                for future in as_completed(futures):
                    try:future.result()
                    except Exception:
                        for queued in futures:queued.cancel()
                        raise
                    snapshot()
        enforce({p['id'] for p in pages})
        with connect() as con:entities=[('ficha',f['id'],ficha_text(f['payload'])) for page in pages for f in con.execute('SELECT id,payload FROM fichas WHERE page_id=?',(page['id'],))]
        build(entities)
        report();snapshot()
    state=snapshot()
    if state['counts'].get('failed',0):raise RuntimeError('Some pages failed validation; see reports/full-book-failures.jsonl and rerun --resume')
    logging.info('FULL BOOK COMPLETE: %s',state['counts'])
