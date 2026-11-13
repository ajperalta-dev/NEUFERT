import pymupdf as fitz
from pipeline import ingest, db

def test_ingest_resume_and_recreate_missing_asset(tmp_path,monkeypatch):
    source=tmp_path/'source.pdf'
    doc=fitz.open();page=doc.new_page()
    page.insert_text((50,50),'STAIRS',fontsize=20)
    page.insert_text((50,100),'Residential stair clear width 1.20 m.',fontsize=12)
    doc.save(source);doc.close()
    monkeypatch.setattr(db,'DB',tmp_path/'library.sqlite')
    monkeypatch.setattr(ingest,'PRIVATE',tmp_path/'private')
    ingest.ingest(source)
    ingest.ingest(source)
    with db.connect() as con:
        assert con.execute('SELECT count(*) FROM entries').fetchone()[0]==1
        assert con.execute('SELECT count(*) FROM entries_fts').fetchone()[0]==1
        image=tmp_path/'private'/con.execute('SELECT image FROM pages').fetchone()[0]
    image.unlink()
    ingest.ingest(source)
    assert image.exists()
    with db.connect() as con:
        assert con.execute('SELECT count(*) FROM dimensions').fetchone()[0]==1
