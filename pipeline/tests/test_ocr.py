"""Optional real Tesseract integration; setup.sh installs the verified German model."""
from pathlib import Path
import shutil
import fitz
import pytest
from pipeline.ingest import ingest
from pipeline.storage import connect

TRAINING=Path(__file__).resolve().parents[2]/'data/private/tessdata/deu.traineddata'

@pytest.mark.skipif(not TRAINING.is_file(),reason='run scripts/setup.sh to install German OCR training')
def test_real_german_scan_ocr(tmp_path,monkeypatch):
    root=tmp_path/'data';(root/'private/tessdata').mkdir(parents=True)
    shutil.copyfile(TRAINING,root/'private/tessdata/deu.traineddata')
    monkeypatch.setenv('NEUFERT_DATA_DIR',str(root))
    original=fitz.open();page=original.new_page()
    page.insert_text((50,90),'Krankenhaus Flur',fontsize=28)
    page.insert_text((50,160),'Die Breite des Flurs ist 2,40 m.',fontsize=22)
    page.insert_text((50,210),'Eine Treppe und ein Bett im Krankenhaus.',fontsize=20)
    image=page.get_pixmap(dpi=180).tobytes('png')
    scan=fitz.open();page=scan.new_page();page.insert_image(page.rect,stream=image)
    source=tmp_path/'synthetic-scan.pdf';scan.save(source);scan.close();original.close()
    result=ingest(source)
    db=connect()
    try:
        page=db.execute('SELECT * FROM pages').fetchone()
        assert page['ocr']==1 and 'Krankenhaus' in page['text']
        assert '2,40' in page['text']
        assert db.execute('SELECT MIN(needs_review) FROM entries').fetchone()[0]==1
    finally: db.close()
