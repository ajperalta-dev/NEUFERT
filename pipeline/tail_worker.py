"""Optional independent tail extraction, defers before the main worker arrives."""
import json
import argparse
import logging
import os
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from pathlib import Path
from .db import connect
from .config import PRIVATE
from .structured_db import select_pages,digest
from .vision_fichas import run

START=400
DEFER_AT=380
WORKERS=2
NAME='tail'

def defer():
    with connect() as con:
        number=con.execute("SELECT max(p.pdf_page) FROM pages p JOIN vision_progress v ON v.page_id=p.id WHERE p.pdf_page<? AND v.status='complete'",(START,)).fetchone()[0]
    return bool(number and number>=DEFER_AT)

def page_job(page):
    if defer():return 'deferred'
    for attempt in range(2):
        try:run([page],resume=True);return 'complete'
        except Exception as error:
            logging.exception('Tail PDF %s attempt %s',page['pdf_page'],attempt+1)
            if getattr(getattr(error,'response',None),'status_code',None) in (401,403,429):raise
            if attempt==0:time.sleep(2)
            else:
                with connect() as con:con.execute('INSERT OR REPLACE INTO vision_progress VALUES(?,?,?,?,?,?,?)',(page['id'],digest(page['text']),os.getenv('NEUFERT_VISION_MODEL','gpt-6-luna'),'failed',0,0,datetime.now(timezone.utc).isoformat()))
                with (PRIVATE/'reports'/f'{NAME}-failures.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps({'pdf_page':page['pdf_page'],'error':str(error)})+'\n')
    return 'failed'

def main():
    global START,DEFER_AT,WORKERS,NAME
    parser=argparse.ArgumentParser()
    parser.add_argument('--pages',default='400-587');parser.add_argument('--defer-at',type=int,default=380)
    parser.add_argument('--workers',type=int,default=2);parser.add_argument('--name',default='tail')
    parser.add_argument('--approved-full-run',action='store_true')
    args=parser.parse_args()
    if not args.approved_full_run:parser.error('Pilot approval and --approved-full-run are required')
    START=int(args.pages.split('-')[0]);DEFER_AT=args.defer_at;WORKERS=args.workers;NAME=args.name
    if not 1<=WORKERS<=4 or not NAME.isalnum() or DEFER_AT>=START:parser.error('Use 1–4 workers, an alphanumeric name and a defer threshold below the page range')
    for line in Path('.env').read_text(encoding='utf-8').splitlines():
        key,sep,value=line.partition('=')
        if sep and key in ('OPENAI_API_KEY','NEUFERT_VISION_MODEL','NEUFERT_VISION_PROVIDER'):os.environ.setdefault(key,value)
    os.environ['NEUFERT_VISION_USAGE_FILE']=f'vision-usage-{NAME}.jsonl'
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s')
    with connect() as con:rows=select_pages(con,args.pages)
    groups=OrderedDict()
    for page in rows:
        if page['chapter']=='REFERENCES':continue
        groups.setdefault((page['chapter'],page['section']),[]).append(page)
    for chapter,pages in groups.items():
        if defer():logging.info('Deferring remaining tail pages to main worker');break
        logging.info('TAIL CHAPTER %s, PDF %s–%s',chapter,pages[0]['pdf_page'],pages[-1]['pdf_page'])
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures=[pool.submit(page_job,page) for page in pages]
            for future in as_completed(futures):
                try:logging.info('Tail result %s',future.result())
                except Exception:
                    for queued in futures:queued.cancel()
                    raise
    logging.info('TAIL WORKER FINISHED; main worker handles embeddings and consolidated reports')
if __name__=='__main__':main()
