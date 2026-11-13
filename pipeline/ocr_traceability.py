"""Preserve source OCR literally; never change numeric values or visual status."""
import csv
import json
import unicodedata
from .config import PRIVATE
from .db import connect

def canonical(text):
    chars=[];positions=[]
    for index,char in enumerate(text):
        for c in unicodedata.normalize('NFKC',char).casefold():
            if c.isspace():continue
            c='.' if c==',' else '-' if c in '–—−' else c
            chars.append(c);positions.append(index)
    return ''.join(chars),positions

def source_span(raw,text):
    if raw and raw in text:return raw,'literal'
    needle,_=canonical(raw);haystack,positions=canonical(text)
    index=haystack.find(needle) if needle else -1
    if index>=0:return text[positions[index]:positions[index+len(needle)-1]+1],'format_normalized'
    return text,'full_page_fallback'

def ficha_text(payload):
    f=json.loads(payload) if isinstance(payload,str) else payload
    fields=[f['title'],f['summary'],f['building_type']]
    for key in ('spaces','uses','furniture_equipment','keywords','tags_architectural','figure_refs','cross_refs'):fields.extend(f[key])
    fields.extend(f"{d['label']}: {d['value']} {d['value_max'] if d['value_max'] is not None else ''} {d['unit']}. {d['context']}" for d in f['dimensions'])
    return '\n'.join(fields)

def enforce(page_ids=None):
    out=PRIVATE/'reports';out.mkdir(exist_ok=True)
    audit_path=out/'ocr-provenance.json'
    audit=json.loads(audit_path.read_text(encoding='utf-8')) if audit_path.exists() else {}
    changed=0
    with connect() as con:
        rows=con.execute('SELECT f.id,f.page_id,f.payload,p.text FROM fichas f JOIN pages p ON p.id=f.page_id').fetchall()
        touched=set()
        for row in rows:
            if page_ids is not None and row['page_id'] not in page_ids:continue
            f=json.loads(row['payload']);dirty=False
            for index,d in enumerate(f['dimensions']):
                key=f"{f['id']}:{index}"
                previous=audit.get(key,{})
                raw=previous.get('model_candidate',d['ocr_raw'])
                exact,method=source_span(raw,row['text'])
                audit[key]={'ficha_id':f['id'],'pdf_page':f['pdf_page'],'dimension_index':index,'label':d['label'],'method':method,'model_candidate':raw}
                if exact!=d['ocr_raw']:d['ocr_raw']=exact;dirty=True
            if dirty:
                con.execute('UPDATE fichas SET payload=? WHERE id=?',(json.dumps(f,ensure_ascii=False),f['id']))
                touched.add((row['page_id'],f['pdf_page']));changed+=1
        for page_id,number in touched:
            fichas=[json.loads(r[0]) for r in con.execute('SELECT payload FROM fichas WHERE page_id=? ORDER BY id',(page_id,))]
            target=PRIVATE/'fichas'/f'p{number:03}.json';temporary=target.with_suffix('.tmp')
            temporary.write_text(json.dumps({'fichas':fichas},ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(target)
    temporary=audit_path.with_suffix('.tmp');temporary.write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(audit_path)
    with (out/'ocr_traceability.csv').open('w',newline='',encoding='utf-8-sig') as stream:
        writer=csv.DictWriter(stream,fieldnames=['ficha_id','pdf_page','dimension_index','label','method','model_candidate']);writer.writeheader();writer.writerows(audit.values())
    return {'updated_fichas':changed,'dimension_records':len(audit),'full_page_fallbacks':sum(r['method']=='full_page_fallback' for r in audit.values())}

if __name__=='__main__':print(json.dumps(enforce()))
