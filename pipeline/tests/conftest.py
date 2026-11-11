import fitz
import pytest
from pipeline.ingest import ingest
from pipeline.storage import connect

@pytest.fixture
def book(tmp_path,monkeypatch):
    monkeypatch.setenv('NEUFERT_DATA_DIR',str(tmp_path/'data'))
    path=tmp_path/'synthetic-not-neufert.pdf'
    doc=fitz.open()
    for number,(title,text) in enumerate([
        ('Krankenhaus Flure','Der Flur im Krankenhaus ist 2,40 m breit. Betten und Bewegung.'),
        ('Wohnhaus Treppen','Die Treppe im Wohnhaus ist 90 cm breit. Wohnen und Arbeiten.')],1):
        page=doc.new_page(width=500,height=700)
        page.insert_text((40,60),title,fontsize=20)
        page.insert_text((40,110),text,fontsize=10)
        page.draw_rect(fitz.Rect(40,160,240,280))
        page.draw_line(fitz.Point(50,170),fitz.Point(230,260))
        page.insert_text((250,680),str(number+100),fontsize=10)
    doc.set_toc([[1,'Krankenhaus',1],[1,'Wohnhaus',2]])
    doc.save(path)
    doc.close()
    result=ingest(path)
    return path,result

@pytest.fixture
def db(book):
    connection=connect()
    yield connection
    connection.close()
