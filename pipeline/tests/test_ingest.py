import json
from pathlib import Path
import pytest
from PIL import Image
from pipeline.ingest import ingest,analyze
from pipeline.extract import dimensions,segment
from pipeline.storage import private_dir

def test_analysis_extraction_geometry_and_files(book,db):
    path,result=book
    report=analyze(path)
    assert report['pages']==2 and report['pages_requiring_ocr']==[]
    assert len(report['toc'])==2
    pages=db.execute('SELECT * FROM pages ORDER BY number').fetchall()
    assert [p['printed'] for p in pages]==['101','102']
    assert all(p['status']=='complete' for p in pages)
    for page in pages:
        with Image.open(private_dir()/page['image']) as image:
            assert image.format=='WEBP' and image.width>1000
        assert json.loads(page['blocks'])[0]['bbox'][0]>0
    row=db.execute('SELECT * FROM entries WHERE page_pdf=1').fetchone()
    assert 'Krankenhaus' in row['title_de']
    assert json.loads(row['dimensions'])[0]['valor']==2.4
    assert json.loads(row['figures'])
    assert row['typology']=='salud'
    assert 'pasillo' in json.loads(row['spaces'])
    assert Path(result['analysis']).is_file()

def test_resume_force_and_personal_data_preserved(book,db):
    path,_=book
    entry=db.execute('SELECT id FROM entries LIMIT 1').fetchone()[0]
    with db:
        db.execute('INSERT INTO favorites VALUES (?)',(entry,))
        db.execute("INSERT INTO collections(id,name) VALUES ('test','My project')")
        db.execute("INSERT INTO collection_entries VALUES ('test',?)",(entry,))
    count=db.execute('SELECT COUNT(*) FROM entries').fetchone()[0]
    assert ingest(path)['skipped']==2
    assert ingest(path,force=True)['processed']==2
    assert db.execute('SELECT COUNT(*) FROM entries').fetchone()[0]==count
    assert db.execute('SELECT COUNT(*) FROM entries_fts').fetchone()[0]==count
    assert db.execute('SELECT COUNT(*) FROM favorites').fetchone()[0]==1
    assert db.execute('SELECT COUNT(*) FROM collection_entries').fetchone()[0]==1

def test_dimensions_do_not_invent_or_confuse_units():
    values=dimensions('Breite 0,90 m, Abstand 25 mm, Fläche 15 m², Winkel 45°. Nummer 1936.')
    assert [(d['valor'],d['unidad']) for d in values]==[(.9,'m'),(25,'mm'),(15,'m²'),(45,'°')]
    assert dimensions('Keine Maße angegeben')==[]

def test_segmentation_and_uncertainty():
    blocks=[{'text':'Treppe','size':20,'bold':True,'bbox':[10,10,90,35]},
            {'text':'Eine lange Beschreibung mit 90 cm Breite.','size':10,'bold':False,'bbox':[10,50,200,70]},
            {'text':'Küche','size':20,'bold':True,'bbox':[10,100,90,125]},
            {'text':'Eine lange Beschreibung für die Küche.','size':10,'bold':False,'bbox':[10,140,200,160]}]
    result=segment(blocks,500,700)
    assert len(result)==2 and result[1]['title']=='Küche'
    assert result[0]['bbox']==[10,10,200,70]
    assert segment([blocks[1]],500,700)[0]['confidence']<.7
    assert segment([],500,700)==[]

def test_resume_after_partial_run(book,db):
    path,result=book
    # Simulate an uncommitted second page; dependent data never becomes marked complete.
    with db:
        db.execute('DELETE FROM pages WHERE document_id=? AND number=2',(result['document_id'],))
    state=ingest(path)
    assert state['skipped']==1 and state['processed']==1


def test_scanned_page_reports_missing_german_ocr(tmp_path,monkeypatch):
    import fitz
    monkeypatch.setenv('NEUFERT_DATA_DIR',str(tmp_path/'data'))
    doc=fitz.open();doc.new_page();source=tmp_path/'blank.pdf';doc.save(source);doc.close()
    monkeypatch.setattr(fitz.Page,'get_textpage_ocr',lambda *a,**kw:(_ for _ in ()).throw(RuntimeError('deu unavailable')))
    assert analyze(source)['pages_requiring_ocr']==[1]
    with pytest.raises(RuntimeError,match='German OCR'):
        ingest(source)
