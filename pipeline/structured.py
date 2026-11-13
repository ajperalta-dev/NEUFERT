import argparse
import json
import logging
import os
import sys
from pathlib import Path
from .config import PRIVATE
from .db import connect
from .structured_db import migrate,select_pages
from .page_embeddings import build,search

def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser()
    parser.add_argument('phase',choices=['migrate','embed','search','pilot','full','report','schema'])
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--chapter');parser.add_argument('--pages');parser.add_argument('--query')
    parser.add_argument('--resume',action='store_true',default=True);parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--batch-size',type=int,default=8);parser.add_argument('--approved-full-run',action='store_true')
    parser.add_argument('--env-file',help='Explicit local KEY=VALUE file; never executed')
    args=parser.parse_args()
    if args.env_file:
        allowed={'OPENAI_API_KEY','NEUFERT_VISION_MODEL','NEUFERT_VISION_PROVIDER','NEUFERT_VISION_URL','NEUFERT_EMBEDDING_PROVIDER','NEUFERT_EMBEDDING_URL','NEUFERT_EMBEDDING_API_KEY'}
        for line in Path(args.env_file).read_text(encoding='utf-8-sig').splitlines():
            key,sep,value=line.partition('=')
            if sep and key.strip() in allowed:os.environ.setdefault(key.strip(),value.strip().strip('\"').strip("'"))
    if args.batch_size<1:parser.error('batch-size must be positive')
    PRIVATE.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO,handlers=[logging.StreamHandler(),logging.FileHandler(PRIVATE/'structured.log',encoding='utf-8')])
    if args.phase=='schema':
        from .ficha_schema import PageFichas
        print(json.dumps(PageFichas.model_json_schema(),indent=2));return
    if args.phase=='migrate':
        if args.dry_run:print('Would add page columns, toc, pages_fts, embeddings, entity_vectors, fichas, vision_progress; preserve original tables.')
        else:migrate()
        return
    with connect() as con:rows=select_pages(con,args.pages or ('39-48' if args.phase=='pilot' else None),args.chapter)
    if args.phase=='full':
        from .full_book import estimate,run_book
        if args.dry_run:print(json.dumps(estimate(rows)));return
        if not args.approved_full_run:parser.error('Full processing requires --approved-full-run after approval of pilot')
        if not 1<=args.workers<=4:parser.error('workers must be 1–4')
        run_book(rows,args.workers);return
    if args.dry_run:
        content=[r for r in rows if r['pdf_page'] not in (1,5,13,607,608)]
        print(json.dumps({'pages':len(rows),'vision_calls':2*len(content) if args.phase=='pilot' else 0,
            'estimated_input_tokens':sum(len(r['text'])//3+6000 for r in content)*2 if args.phase=='pilot' else None,
            'estimate_note':'Planning estimate, not provider billing; image tokens depend on the selected model and retries add calls.',
            'estimated_output_token_cap':24000*len(content) if args.phase=='pilot' else None,
            'cost':'Requires provider rates; actual usage logged per call','embedding_provider':os.getenv('NEUFERT_EMBEDDING_PROVIDER','local')}));return
    if args.phase=='embed':
        from .ocr_traceability import ficha_text
        entities=[('page',r['id'],r['text']) for r in rows]
        with connect() as con:
            for row in rows:entities.extend(('ficha',f['id'],ficha_text(f['payload'])) for f in con.execute('SELECT id,payload FROM fichas WHERE page_id=?',(row['id'],)))
        build(entities,args.batch_size)
    elif args.phase=='search':print(json.dumps(search(args.query or '',chapter=args.chapter,pages=args.pages),ensure_ascii=False,indent=2))
    elif args.phase=='pilot':
        if not args.approved_full_run and any(not 39<=r['pdf_page']<=48 for r in rows):parser.error('Only pilot PDF 39–48 is authorized until explicit approval')
        from .vision_fichas import run,report
        from .ocr_traceability import enforce,ficha_text
        run(rows,resume=args.resume)
        enforce({row['id'] for row in rows});report()
        with connect() as con:entities=[('ficha',f['id'],ficha_text(f['payload'])) for row in rows for f in con.execute('SELECT id,payload FROM fichas WHERE page_id=?',(row['id'],))]
        build(entities,args.batch_size)
    elif args.phase=='report':
        from .vision_fichas import report
        report()

if __name__=='__main__':main()
