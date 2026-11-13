import json
from pipeline import base_package
from pipeline.db import connect,initialize

def test_word_coordinates_keep_normalized_positions(tmp_path,monkeypatch):
    monkeypatch.setattr(base_package,'PRIVATE',tmp_path)
    words=tmp_path/'base-package'/'words';words.mkdir(parents=True)
    payload={'page':40,'words':[['Universal',.1,.2,.3,.25],['standard',.31,.2,.5,.25],['stairs',.2,.4,.3,.5]]}
    (words/'p040.json').write_text(json.dumps(payload))
    assert base_package.matches(40,'universal')['matches']==[payload['words'][0]]
    assert base_package.matches(40,'escalera')['matches']==[payload['words'][2]]
    assert base_package.matches(40,'')['matches']==[]
    assert base_package.matches(40,'unknown')['total']==0

def test_package_metadata_is_scoped_to_document(tmp_path):
    path=tmp_path/'library.sqlite';initialize(path)
    with connect(path) as con:
        original={'document_id':'original','pagina_pdf':40,'image':'old.webp','pagina_impresa':None}
        assert base_package.decorate(con,original.copy())==original
        con.executescript(base_package.SCHEMA)
        metadata={'image':'base-package/pages/p040.webp','thumbnail':'base-package/thumbs/p040.webp','chapter':'BASICS','section':'Relationships','book_page':27}
        con.execute('INSERT INTO base_package_pages VALUES(?,?,?)',('original',40,json.dumps(metadata)))
        decorated=base_package.decorate(con,original.copy())
        assert decorated['pagina_impresa']=='27'
        assert decorated['image']==metadata['image']
        assert decorated['section']=='Relationships'
        assert base_package.metadata(con,'different-document',40) is None
