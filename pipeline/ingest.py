"""python -m pipeline.ingest [--limit 20] [--embeddings] [--ocr-language eng]"""
import argparse
import hashlib
import json
import logging
import os
import re
from pathlib import Path
import pymupdf as fitz
from .config import PRIVATE, SOURCE, VERSION
from .db import connect, initialize
from .extract import text_blocks, printed_number, segment, dimensions, render, figure_boxes
from .taxonomy import match_terms, translated_title, TERMS

log=logging.getLogger('neufert.ingest')
J=lambda value:json.dumps(value,ensure_ascii=False)

def source_metadata(doc):
    front='\n'.join(doc[i].get_text() for i in range(min(12,len(doc))))
    english='English language first published 2012' in front
    edition='4th English edition (2012), based on 39th German edition' if english else 'Edition unverified'
    return ('en' if english else 'de'), edition

def contents(doc):
    native=doc.get_toc()
    if native:
        return [{'title':t,'page_pdf':p,'level':level} for level,t,p in native]
    entries=[]
    for i in range(min(12,len(doc))):
        for line in doc[i].get_text().splitlines():
            m=re.match(r'^(.{3,100}?)\s*\.{3,}.*?\s(\d{1,3})\s*$',line)
            if m: entries.append({'title':m[1].strip(),'page_printed':int(m[2]),'source_page':i+1,'level':1})
    return entries

def ingest(source=SOURCE,limit=None,ocr_language=None,tables=False):
    PRIVATE.mkdir(parents=True,exist_ok=True)
    initialize()
    digest=hashlib.sha256(Path(source).read_bytes()).hexdigest()
    with fitz.open(source) as doc, connect(vectors=True) as con:
        language,edition=source_metadata(doc)
        outline=contents(doc)
        con.execute('INSERT OR IGNORE INTO documents VALUES(?,?,?,?,?,?,?)',
                    (digest,Path(source).name,language,edition,len(doc),J(doc.metadata),J(outline)))
        con.commit()
        previous=''
        for page in list(doc)[:limit]:
            number=page.number+1
            page_id=f'{digest[:16]}-{number}'
            directory=PRIVATE/digest[:16]
            image=f'{digest[:16]}/pages/{number:04}.webp'
            old=con.execute('SELECT version FROM pages WHERE id=?',(page_id,)).fetchone()
            assets=[image]+[r[0] for r in con.execute('SELECT f.image FROM figures f JOIN entries e ON e.id=f.entry_id WHERE e.page_id=?',(page_id,))]
            if old and old[0]==VERSION and all((PRIVATE/a).exists() for a in assets):
                log.info('Page %s/%s already complete',number,len(doc))
                continue
            try:
                blocks,ocr=text_blocks(page,ocr_language or language.replace('en','eng').replace('de','deu'))
                printed=printed_number(blocks,page.rect.height)
                chunks=segment(blocks,page.rect.width,page.rect.height)
                # Heading from actual printed TOC when there is an exact match.
                titles=[x['title'] for x in outline if str(x.get('page_printed'))==printed]
                if titles: chunks[0]['title']=titles[0]
                render(page,PRIVATE/image)
                boxes=figure_boxes(page)
                figures=[]
                for fi,(box,method) in enumerate(boxes):
                    asset=f'{digest[:16]}/figures/{number:04}-{fi}.webp'
                    render(page,PRIVATE/asset,bbox=box)
                    figures.append((box,asset,method))
                table_data=[]
                if tables:
                    import pdfplumber
                    with pdfplumber.open(source) as plumber:
                        table_data=plumber.pages[page.number].extract_tables()
                with con:
                    ids=[r[0] for r in con.execute('SELECT id FROM entries WHERE page_id=?',(page_id,))]
                    for eid in ids:
                        for r in con.execute('SELECT id FROM embedding_chunks WHERE entry_id=?',(eid,)).fetchall():
                            con.execute('DELETE FROM vectors WHERE rowid=?',(r[0],))
                        con.execute('DELETE FROM embedding_chunks WHERE entry_id=?',(eid,))
                        con.execute('DELETE FROM entries_fts WHERE id=?',(eid,))
                        con.execute('DELETE FROM figures WHERE entry_id=?',(eid,))
                        con.execute('DELETE FROM dimensions WHERE entry_id=?',(eid,))
                        con.execute('DELETE FROM tags WHERE entry_id=?',(eid,))
                    con.execute('INSERT INTO pages(id,document_id,number,printed,width,height,text,blocks,tables_json,image,version) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET printed=excluded.printed,text=excluded.text,blocks=excluded.blocks,tables_json=excluded.tables_json,image=excluded.image,version=excluded.version',
                                (page_id,digest,number,printed,page.rect.width,page.rect.height,'\n'.join(b['text'] for b in blocks),J(blocks),J(table_data),image,VERSION))
                    for ci,chunk in enumerate(chunks):
                        eid=f'{page_id}-{ci}'
                        translations=translated_title(chunk['title'],language)
                        # Existing OCR is uncertain even when it contains many chars.
                        confidence=.58 if page.get_images() else .82
                        if len(chunk['text'])<100 or ocr: confidence=min(confidence,.4)
                        con.execute('INSERT INTO entries VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,title_de=excluded.title_de,title_es=excluded.title_es,title_en=excluded.title_en,text=excluded.text,bbox=excluded.bbox,confidence=excluded.confidence,section=excluded.section',
                                    (eid,page_id,chunk['title'],translations['de'],translations['es'],translations['en'],chunk['text'],J(chunk['bbox']),confidence,int(confidence<.75),chunk['title']))
                        tags=match_terms(chunk['title']+' '+chunk['text'])
                        con.executemany('INSERT INTO tags VALUES(?,?,?)',[(eid,k,v) for k,v in tags])
                        for measure in dimensions(chunk['text']):
                            con.execute('INSERT INTO dimensions(entry_id,name,value,unit,context,metres) VALUES(?,?,?,?,?,?)',
                                        (eid,measure['nombre'],measure['valor'],measure['unidad'],measure['contexto'],measure['metres']))
                        for fi,(box,asset,method) in enumerate(figures):
                            con.execute('INSERT INTO figures VALUES(?,?,?,?,?)',(f'{eid}-{fi}',eid,J(box),asset,method))
                        tagtext=' '.join(' '.join(TERMS[k][v]) for k,v in tags)
                        con.execute('INSERT INTO entries_fts VALUES(?,?,?,?)',(eid,chunk['title'],chunk['text'],tagtext))
                log.info('Page %s/%s: %s chars, %s figures, printed=%s',number,len(doc),sum(len(b['text']) for b in blocks),len(figures),printed)
            except Exception:
                log.exception('Page %s failed; rerun resumes here',number)
                raise
    return digest

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,default=SOURCE)
    parser.add_argument('--limit',type=int)
    parser.add_argument('--ocr-language',default=os.environ.get('NEUFERT_OCR_LANG'))
    parser.add_argument('--tables',action='store_true')
    parser.add_argument('--embeddings',action='store_true')
    args=parser.parse_args()
    PRIVATE.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s',handlers=[logging.StreamHandler(),logging.FileHandler(PRIVATE/'ingest.log',encoding='utf-8')])
    ingest(args.source,args.limit,args.ocr_language,args.tables)
    from .export_entries import export_all
    export_all()
    if args.embeddings:
        from .vectors import build
        build()

if __name__=='__main__':main()


