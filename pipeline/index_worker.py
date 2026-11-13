"""Index already validated auxiliary pages while the main vision run advances."""
import logging
import time
from .db import connect
from .structured_db import digest
from .page_embeddings import build

def main():
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s')
    while True:
        with connect() as con:
            primary=con.execute("SELECT max(p.pdf_page) FROM pages p JOIN vision_progress v ON v.page_id=p.id WHERE p.pdf_page<300 AND v.status='complete'").fetchone()[0]
            if primary and primary>=260:break
            existing={r['id_entidad']:r['source_hash'] for r in con.execute("SELECT id_entidad,source_hash FROM embeddings WHERE entidad='ficha'")}
            rows=con.execute('SELECT f.id,f.payload FROM fichas f JOIN pages p ON p.id=f.page_id WHERE p.pdf_page>=300 ORDER BY p.pdf_page,f.id').fetchall()
            pending=[('ficha',r['id'],r['payload']) for r in rows if existing.get(r['id'])!=digest(r['payload'])][:32]
        if pending:build(pending)
        else:time.sleep(5)
    logging.info('Auxiliary indexing handed back to main worker')
if __name__=='__main__':main()
