from pipeline.verify_pass2 import locate,Reading,decide,migrate

def test_locator_unique_and_ambiguous():
 d={'value':1.2,'label':'width'}
 assert locate([['1,20',.1,.2,.2,.3]],d)[0]=='exact_words'
 assert locate([['1.20',.1,.2,.2,.3],['1.20',.5,.6,.6,.7]],d)==('tiles',None)

def test_decision_units_ranges_and_corrected():
 d={'value':1.2,'value_max':1.8,'unit':'m','status':'uncertain'}
 assert decide(d,Reading(printed='120–180',unit='cm',reason='visible'),None)[0]=='verified'
 assert decide(d,Reading(printed='100',unit='cm',reason='visible'),None)[0]=='uncertain'
 d.update(value=1,value_max=None,status='corrected')
 assert decide(d,Reading(printed='100',unit='cm',reason='visible'),None)[0]=='corrected'
 assert decide(d,Reading(printed='',unit='',unreadable=True,reason='blur'),None)[0]=='uncertain'

def test_migration_twice(tmp_path,monkeypatch):
 import pipeline.verify_pass2 as m
 from pipeline.db import connect
 monkeypatch.setattr(m,'PRIVATE',tmp_path)
 monkeypatch.setattr(m,'connect',lambda:connect(tmp_path/'db.sqlite'))
 migrate();migrate()
 with connect(tmp_path/'db.sqlite') as c:assert c.execute('select count(*) from verification_pass2').fetchone()[0]==0

def test_endpoint_filters(monkeypatch):
 from fastapi.testclient import TestClient
 from pipeline.api import app
 from pipeline import hybrid_api
 monkeypatch.setattr(hybrid_api,'results',lambda q,chapter,kind,uncertain,limit:{'items':[],'query':q,'kind':kind,'include_uncertain':uncertain})
 r=TestClient(app).get('/api/search',params={'q':'hospital','result_type':'ficha','include_uncertain':'false'})
 assert r.status_code==200 and r.json()['kind']=='ficha' and r.json()['include_uncertain'] is False
 assert TestClient(app).get('/api/search?result_type=invalid').status_code==422
