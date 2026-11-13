"""Register a prepared package without opening or processing the PDF."""
import argparse
import json
import re
import shutil
from pathlib import Path
from .config import PRIVATE
from .db import connect
from .taxonomy import expand_query, normalize

SCHEMA='''CREATE TABLE IF NOT EXISTS base_package_pages(
document_id TEXT,number INTEGER,metadata TEXT NOT NULL,
PRIMARY KEY(document_id,number));
CREATE TABLE IF NOT EXISTS base_package_toc(document_id TEXT PRIMARY KEY,outline TEXT NOT NULL);'''

def register(source):
    source=Path(source).resolve()
    if not (source/'pages_index.json').exists():source=source/'neufert'
    pages=json.loads((source/'pages_index.json').read_text(encoding='utf-8'))
    toc=json.loads((source/'toc.json').read_text(encoding='utf-8'))
    assert len(pages)==608 and {p['pdf_page'] for p in pages}==set(range(1,609)), 'Expected 608 unique pages'
    for page in pages:
        n=page['pdf_page']
        for relative in (page['file'],page['thumb'],f'text/p{n:03}.txt',f'words/p{n:03}.json'):
            path=(source/relative).resolve()
            if not path.is_relative_to(source) or not path.is_file():raise ValueError(f'Invalid/missing asset: {relative}')
    with connect() as con:
        docs=con.execute("SELECT id FROM documents WHERE pages=608 AND edition LIKE '4th English edition%'").fetchall()
        if len(docs)!=1:raise ValueError('Expected one matching English Neufert document')
        doc=docs[0][0]
        # Verify identity against already ingested OCR, never reopen the PDF.
        for n in (40,148,304):
            previous=con.execute('SELECT text FROM pages WHERE document_id=? AND number=?',(doc,n)).fetchone()
            old=set(re.findall(r'\w+',normalize(previous[0]))) if previous else set()
            new=set(re.findall(r'\w+',normalize((source/f'text/p{n:03}.txt').read_text(encoding='utf-8'))))
            if len(old & new)/max(1,len(old | new))<.7:raise ValueError(f'OCR identity check failed on page {n}')
        target=PRIVATE/'base-package'
        target.mkdir(parents=True,exist_ok=True)
        for directory in ('pages','thumbs','text','words'):
            shutil.copytree(source/directory,target/directory,dirs_exist_ok=True)
        for name in ('pages_index.json','toc.json','search_text.json','README.md'):
            shutil.copy2(source/name,target/name)
        con.executescript(SCHEMA)
        for page in pages:
            metadata={**page,'image':'base-package/'+page['file'],'thumbnail':'base-package/'+page['thumb']}
            con.execute('INSERT OR REPLACE INTO base_package_pages VALUES(?,?,?)',(doc,page['pdf_page'],json.dumps(metadata)))
        outline=[{**entry,'page_pdf':entry['pdf_page']} for entry in toc['toc']]
        con.execute('INSERT OR REPLACE INTO base_package_toc VALUES(?,?)',(doc,json.dumps(outline)))
    print(f'Registered {len(pages)} pages and {len(outline)} index entries in {target}')

def metadata(con,doc,number):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='base_package_pages'").fetchone():return None
    row=con.execute('SELECT metadata FROM base_package_pages WHERE document_id=? AND number=?',(doc,number)).fetchone()
    return json.loads(row[0]) if row else None

def decorate(con,item):
    data=metadata(con,item['document_id'],item.get('pagina_pdf',item.get('number')))
    if data:
        item.update(image=data['image'],thumbnail=data['thumbnail'],chapter=data['chapter'],section=data['section'],
                    pagina_impresa=str(data['book_page']) if data['book_page'] is not None else None)
    return item

def matches(number,query):
    path=PRIVATE/'base-package'/'words'/f'p{number:03}.json'
    words=json.loads(path.read_text(encoding='utf-8'))['words']
    tokens=set(expand_query(query)) if query.strip() else set()
    selected=[word for word in words if any(t in tokens for t in re.findall(r'\w+',normalize(word[0])))]
    return {'matches':selected[:2000],'total':len(selected),'truncated':len(selected)>2000}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source');register(parser.parse_args().source)
