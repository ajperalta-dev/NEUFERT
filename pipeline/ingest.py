import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import fitz
from PIL import Image
from .storage import connect, data_dir, private_dir, save_entry
from .extract import text_blocks, segment, enrich, printed_page

VERSION = '1'
log = logging.getLogger('ingest')

def fingerprint(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()

def analyze(source):
    with fitz.open(source) as doc:
        if doc.needs_pass:
            raise ValueError('PDF encrypted: supply an unlocked local copy.')
        counts = [len(p.get_text().strip()) for p in doc]
        return {'pages': len(doc), 'metadata': doc.metadata, 'toc': doc.get_toc(),
                'text_characters_per_page': counts,
                'pages_requiring_ocr': [i+1 for i,n in enumerate(counts) if n < 50],
                'note': 'OCR threshold is a heuristic; inspect sparse diagram pages manually.'}

def webp(page, destination, clip=None):
    pix = page.get_pixmap(dpi=150, clip=clip, alpha=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix('.tmp')
    Image.frombytes('RGB', [pix.width,pix.height], pix.samples).save(temporary, 'WEBP', quality=85)
    temporary.replace(destination)

def figure_boxes(page):
    boxes = [fitz.Rect(x['bbox']) for x in page.get_image_info()]
    boxes += [fitz.Rect(r) for r in page.cluster_drawings()]
    result = []
    for box in boxes:
        box &= page.rect
        if box.width < 25 or box.height < 25 or box.get_area() > page.rect.get_area()*.95:
            continue
        if not any((box & other).get_area() / max(box.get_area(),1) > .9 for other in result):
            result.append(box)
    return sorted(result, key=lambda b: (b.y0,b.x0))

def ingest(source=None, force=False, limit=None, ocr='auto'):
    source = Path(source or data_dir() / 'source/neufert.pdf').resolve()
    report = analyze(source)  # Inspect before writing anything.
    doc_id = fingerprint(source)
    root = private_dir()
    report_path = root / 'documents' / doc_id / 'analysis.json'
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    db = connect()
    try:
        previous = db.execute('SELECT pipeline_version FROM documents WHERE id=?',(doc_id,)).fetchone()
        if previous and previous[0] != VERSION:
            raise ValueError('Pipeline version changed. Rebuild into a new NEUFERT_DATA_DIR; preserve personal collections.')
        with db:
            db.execute('INSERT OR IGNORE INTO documents(id,filename,page_count,metadata,pipeline_version) VALUES (?,?,?,?,?)',
                       (doc_id,str(source),report['pages'],json.dumps(report['metadata']),VERSION))
        processed = skipped = 0
        with fitz.open(source) as doc:
            for index in range(min(len(doc),limit or len(doc))):
                number = index+1
                existing = db.execute('SELECT status FROM pages WHERE document_id=? AND number=?',(doc_id,number)).fetchone()
                if existing and existing[0] == 'complete' and not force:
                    skipped += 1
                    continue
                page = doc[index]
                use_ocr = ocr == 'always' or (ocr == 'auto' and len(page.get_text().strip()) < 50)
                if use_ocr:
                    try:
                        tessdata = str(root/'tessdata') if (root/'tessdata/deu.traineddata').is_file() else None
                        textpage = page.get_textpage_ocr(language='deu', dpi=150, full=True, tessdata=tessdata)
                    except Exception as exc:
                        raise RuntimeError(f'Page {number}: German OCR requires Tesseract deu traineddata; {exc}') from exc
                else:
                    textpage = page.get_textpage()
                blocks = text_blocks(page.get_text('dict',textpage=textpage))
                printed = printed_page(page,blocks)
                folder = Path('documents') / doc_id / f'page-{number:04d}'
                image = folder / 'page.webp'
                webp(page,root/image)
                figures = []
                for i,box in enumerate(figure_boxes(page)):
                    relative = folder / f'figure-{i:03d}.webp'
                    webp(page,root/relative,box)
                    figures.append({'path':str(relative),'bbox':list(box),'page_pdf':number,
                                    'kind':'automatic candidate; verify crop'})
                # Keep a full page candidate for image-only scans, clearly marked.
                if use_ocr and not figures:
                    figures = [{'path':str(image),'bbox':list(page.rect),'page_pdf':number,'kind':'scanned page'}]
                tables = []
                if not use_ocr:
                    try:
                        tables = [{'bbox':list(t.bbox),'rows':t.extract()} for t in page.find_tables().tables]
                    except (ValueError, RuntimeError) as exc:
                        log.warning('Table extraction page %s: %s',number,exc)
                entries = []
                for i,section in enumerate(segment(blocks,page.rect.width,page.rect.height)):
                    item = enrich(section)
                    if use_ocr:
                        item['confidence'] = min(item['confidence'],.6)
                        item['needs_review'] = 1
                    rect = fitz.Rect(item['bbox'])
                    item.update(id=f'{doc_id[:16]}-{number}-{i}', document_id=doc_id,
                                page_pdf=number,page_printed=printed,
                                figures=[f for f in figures if fitz.Rect(f['bbox']).intersects(rect)])
                    entries.append(item)
                # A page is committed atomically. Interrupted/uncommitted pages are safe to retry.
                with db:
                    old_ids = [r[0] for r in db.execute('SELECT id FROM entries WHERE document_id=? AND page_pdf=?',(doc_id,number))]
                    for entry_id in old_ids:
                        db.execute('DELETE FROM entries_fts WHERE id=?',(entry_id,))
                        db.execute('DELETE FROM entry_vectors WHERE entry_id=?',(entry_id,))
                        db.execute('DELETE FROM vector_metadata WHERE entry_id=?',(entry_id,))
                    new_ids = {e['id'] for e in entries}
                    for entry_id in old_ids:
                        if entry_id not in new_ids:
                            db.execute('DELETE FROM entries WHERE id=?',(entry_id,))
                    for item in entries:
                        save_entry(db,item)
                    db.execute('INSERT OR REPLACE INTO pages VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                               (doc_id,number,printed,page.rect.width,page.rect.height,
                                '\n\n'.join(b['text'] for b in blocks),json.dumps(blocks),str(image),
                                json.dumps(tables),int(use_ocr),'complete'))
                processed += 1
                log.info('page %d/%d: %d entries, %d figure candidates, OCR=%s',number,len(doc),len(entries),len(figures),use_ocr)
        return {'document_id':doc_id,'processed':processed,'skipped':skipped,'analysis':str(report_path)}
    finally:
        db.close()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source',type=Path)
    parser.add_argument('--analyze',action='store_true')
    parser.add_argument('--force',action='store_true')
    parser.add_argument('--limit',type=int)
    parser.add_argument('--ocr',choices=['auto','always','never'],default='auto')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s')
    if args.limit is not None and args.limit < 1:
        parser.error('--limit must be positive')
    result = analyze(args.source or data_dir()/'source/neufert.pdf') if args.analyze else ingest(args.source,args.force,args.limit,args.ocr)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__ == '__main__':
    main()
