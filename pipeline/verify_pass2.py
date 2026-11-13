"""Resumable, blind verification of pending dimensions using original PDF crops."""
import argparse,json,os,re,sqlite3,math,csv,logging
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter,defaultdict
import fitz,httpx
from pydantic import BaseModel,Field
from .config import PRIVATE,SOURCE
from .db import connect
from .vision_fichas import VisionProvider,validated,report

class Reading(BaseModel):
    printed:str
    unit:str=''
    unreadable:bool=False
    reason:str
class Location(BaseModel):
    tile:int=Field(ge=0,le=8)
    bbox:list[float]=Field(min_length=4,max_length=4)
    found:bool

def norm(s):return re.sub(r'[^0-9.a-z-]','',str(s).lower().replace(',','.').replace('Ã¢â‚¬â€œ','-').replace('Ã¢Ë†â€™','-'))
def locate(words,d):
    target=norm(d['value']);target=target[:-2] if target.endswith('.0') else target
    hits=[]
    for w in words:
        number=re.match(r'^(\d+(?:[.,]\d+)?)',w[0])
        if number and float(number[1].replace(',','.'))==d['value']:hits.append(w)
    if len(hits)==1:return 'exact_words',hits[0][1:]
    if hits:
        labels=set(re.findall(r'[a-z]{4,}',d['label'].lower()))
        anchors=[w for w in words if norm(w[0]) in labels]
        if anchors:
            distances=sorted((min(math.dist(((w[1]+w[3])/2,(w[2]+w[4])/2),((a[1]+a[3])/2,(a[2]+a[4])/2)) for a in anchors),i) for i,w in enumerate(hits))
            if distances[0][0]<.15 and (len(distances)==1 or distances[1][0]-distances[0][0]>.03):return 'fuzzy_words',hits[distances[0][1]][1:]
    return 'tiles',None

def numbers(text):
    return [float(v.replace(',','.')) for v in re.findall(r'(?<![\w.])-?\d+(?:[.,]\d+)?',text.replace('Ã¢â‚¬â€œ',' - ').replace('Ã¢Ë†â€™','-'))]
def equivalent(read,d):
    vals=numbers(read.printed)
    expected=[d['value']]+([d['value_max']] if d.get('value_max') is not None else [])
    scale={'m':1,'cm':.01,'mm':.001}
    ru=read.unit.strip().lower();du=d['unit'].strip().lower()
    if ru!=du and not (ru in scale and du in scale):return False
    factor=scale.get(ru,1)/scale.get(du,1)
    return len(vals)==len(expected) and all(math.isclose(abs(a)*factor,abs(b),rel_tol=1e-6,abs_tol=1e-8) and (a>=0)==(b>=0) for a,b in zip(vals,expected))
def decide(d,read,candidate):
    if read.unreadable:return 'uncertain','unreadable',False
    if equivalent(read,d):return ('corrected' if d['status']=='corrected' else 'verified'),'Blind reading agrees with current value',False
    if d['status']!='corrected' and candidate:
        c=dict(d);v=numbers(candidate)
        if len(v) in (1,2):
            c['value']=v[0];c['value_max']=v[1] if len(v)==2 else None
            if equivalent(read,c):return 'corrected','Blind reading agrees with first-pass candidate',c
    return 'uncertain','Blind reading disagrees with candidate or unit',False

def migrate():
    with connect() as c:
        backup=PRIVATE/'before-pass2.sqlite3'
        if not backup.exists():
            with sqlite3.connect(backup) as dest:c.backup(dest)
        c.execute('CREATE TABLE IF NOT EXISTS verification_pass2(id TEXT PRIMARY KEY,ficha_id TEXT,dimension_index INTEGER,payload TEXT)')

def load(args):
    with connect() as c:rows=c.execute('SELECT id,payload FROM fichas').fetchall()
    result=[];sample=args.include_verified_sample
    from .structured_db import select_pages
    with connect() as c:allowed={p['pdf_page'] for p in select_pages(c,args.pages,args.chapter)}
    for row in rows:
        f=json.loads(row['payload'])
        if f['pdf_page'] not in allowed:continue
        for i,d in enumerate(f['dimensions']):
            if d['status'] not in ('uncertain','corrected') and not (args.force and d.get('verification_pass2')):
                if sample<=0:continue
                sample-=1
            result.append((f,i,d))
    return result

def crop(page,bbox,path):
    rect=page.rect
    b=fitz.Rect(bbox[0]*rect.width,bbox[1]*rect.height,bbox[2]*rect.width,bbox[3]*rect.height)
    margin=max(48,.15*max(b.width,b.height)) # 48 PDF points = 200 pixels at 300 ppi
    b=fitz.Rect(b.x0-margin,b.y0-margin,b.x1+margin,b.y1+margin)&rect
    pix=page.get_pixmap(matrix=fitz.Matrix(300/72,300/72),clip=b,colorspace=fitz.csGRAY);pix.set_dpi(300,300);pix.save(path)
    return [b.x0/rect.width,b.y0/rect.height,b.x1/rect.width,b.y1/rect.height]

def main():
    p=argparse.ArgumentParser();p.add_argument('--pages');p.add_argument('--chapter');p.add_argument('--dry-run',action='store_true');p.add_argument('--resume',action='store_true');p.add_argument('--force',action='store_true');p.add_argument('--approved-full-run',action='store_true');p.add_argument('--include-verified-sample',type=int,default=0);p.add_argument('--env-file');a=p.parse_args()
    if a.env_file:
        for line in Path(a.env_file).read_text(encoding='utf-8-sig').splitlines():
            k,sep,v=line.partition('=')
            if sep and k.strip() in ('OPENAI_API_KEY','NEUFERT_VERIFY_MODEL','NEUFERT_VISION_MODEL','NEUFERT_VISION_URL'):os.environ.setdefault(k.strip(),v.strip().strip('"').strip("'"))
    records=load(a)
    if not a.force:
        with connect() as c:
            exists=c.execute("SELECT 1 FROM sqlite_master WHERE name='verification_pass2'").fetchone()
            done={r[0] for r in c.execute('SELECT id FROM verification_pass2')} if exists else set()
        records=[r for r in records if f"{r[0]['id']}:{r[1]}" not in done]
    methods=Counter();states=Counter()
    for f,i,d in records:
        ws=json.loads((PRIVATE/'base-package/words'/f"p{f['pdf_page']:03}.json").read_text(encoding="utf-8"))['words'];methods[locate(ws,d)[0]]+=1;states[d['status']]+=1
    if a.dry_run:
        print(json.dumps({'dimensions':len(records),'states':dict(states),'locators':dict(methods),'minimum_calls':len(records)+methods['tiles'],'estimated_input_tokens':len(records)*2000+methods['tiles']*18000,'estimated_output_tokens':len(records)*200,'note':'Image token estimates; tiles/retries may add calls. No API calls made.'}));return
    if not a.approved_full_run and any(not 39<=f['pdf_page']<=48 for f,_,_ in records):p.error('Only PDF 39-48 pilot authorized; use --approved-full-run after approval')
    migrate();out=PRIVATE/'crops';out.mkdir(exist_ok=True);reports=PRIVATE/'reports';reports.mkdir(exist_ok=True)
    original=os.getenv('NEUFERT_VISION_MODEL','gpt-6-luna');os.environ['NEUFERT_VISION_MODEL']=os.getenv('NEUFERT_VERIFY_MODEL',original);os.environ['NEUFERT_VISION_USAGE_FILE']='vision-usage-pass2.jsonl'
    provider=VisionProvider();warning='Same model as first pass; independent cropped prompt only.' if provider.model==original else ''
    doc=fitz.open(SOURCE);provenance=json.loads((reports/'ocr-provenance.json').read_text(encoding="utf-8"));audit=[]
    for f,i,d in records:
        key=f"{f['id']}:{i}"
        with connect() as c:
            previous=c.execute('SELECT payload FROM verification_pass2 WHERE id=?',(key,)).fetchone()
        if previous and not a.force:continue
        try:
            page=doc[f['pdf_page']-1];ws=json.loads((PRIVATE/'base-package/words'/f"p{f['pdf_page']:03}.json").read_text(encoding="utf-8"))['words'];method,bbox=locate(ws,d)
            if bbox is None:
                tiles=[]
                for n in range(9):
                    x=n%3;y=n//3;b=[max(0,x/3-.025),max(0,y/3-.025),min(1,(x+1)/3+.025),min(1,(y+1)/3+.025)];tp=out/f"p{f['pdf_page']:03}_tile{n}.png"
                    if not tp.exists():page.get_pixmap(matrix=fitz.Matrix(300/72,300/72),clip=fitz.Rect(b[0]*page.rect.width,b[1]*page.rect.height,b[2]*page.rect.width,b[3]*page.rect.height),colorspace=fitz.csGRAY).save(tp)
                    tiles.append(tp)
                # Contact sheet preserves all nine original 300ppi tile renders.
                from PIL import Image,ImageDraw
                sheet=Image.new('RGB',(2400,3300),'white')
                for n,tp in enumerate(tiles):
                    im=Image.open(tp);im.thumbnail((790,1060));xy=(n%3*800,n//3*1100);sheet.paste(im,(xy[0],xy[1]+30));ImageDraw.Draw(sheet).text(xy,str(n),fill='black')
                sp=out/f"p{f['pdf_page']:03}_tiles.png";sheet.save(sp)
                loc,_=validated(provider,sp.read_bytes(),'Locate the dimension by label/context ONLY. Do not guess. Return tile index 0-8 and normalized bbox within that tile. Label: '+re.sub(r'\d+(?:[.,]\d+)?','[redacted]',d['label'])+' Context: '+re.sub(r'\d+(?:[.,]\d+)?','[redacted]',d['context'])+' Schema: '+json.dumps(Location.model_json_schema()),Location)
                if not loc.found:raise ValueError('Dimension not located in tiles')
                x=loc.tile%3;y=loc.tile//3;tb=[max(0,x/3-.025),max(0,y/3-.025),min(1,(x+1)/3+.025),min(1,(y+1)/3+.025)]
                bbox=[tb[0]+loc.bbox[0]*(tb[2]-tb[0]),tb[1]+loc.bbox[1]*(tb[3]-tb[1]),tb[0]+loc.bbox[2]*(tb[2]-tb[0]),tb[1]+loc.bbox[3]*(tb[3]-tb[1])]
            if not all(0<=v<=1 for v in bbox) or bbox[2]<=bbox[0] or bbox[3]<=bbox[1]:raise ValueError('Invalid locator bbox')
            cp=out/f"p{f['pdf_page']:03}_{f['id']}_{i}.png";actual=crop(page,bbox,cp)
            # Context can contain candidate numbers: remove all numeric expressions before blind reading.
            context=re.sub(r'\d+(?:[.,]\d+)?','[redacted]',d['context']);label=re.sub(r'\d+(?:[.,]\d+)?','[redacted]',d['label'])
            read,_=validated(provider,cp.read_bytes(),'Read ONLY the explicitly printed number/range and unit corresponding to label '+label+'; context '+context+'. No calculations or inferred values. If ambiguous set unreadable=true. Schema: '+json.dumps(Reading.model_json_schema()),Reading)
            status,reason,change=decide(d,read,provenance.get(key,{}).get('model_candidate'))
            record={'model':provider.model,'locator':method,'bbox':bbox,'crop_bbox':actual,'crop_path':str(cp.relative_to(PRIVATE)),'read_value':read.model_dump(),'outcome':status,'reason':reason,'timestamp':datetime.now(timezone.utc).isoformat(),'warning':warning,'before':dict(d)}
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401,403,429):raise
            logging.exception(key);continue
        except Exception as e:
            logging.exception(key);record={'model':provider.model,'locator':method,'bbox':bbox,'outcome':'uncertain','reason':str(e),'before':dict(d),'timestamp':datetime.now(timezone.utc).isoformat(),'warning':warning};status='uncertain';change=False
        with connect() as c:
            current=json.loads(c.execute('SELECT payload FROM fichas WHERE id=?',(f['id'],)).fetchone()[0]);dim=current['dimensions'][i]
            dim.setdefault('status_history',[]).append({'status':dim['status'],'value':dim['value'],'value_max':dim.get('value_max'),'timestamp':record['timestamp']})
            dim.setdefault('original_value',dim['value']);dim['status']=status;dim['verification_pass2']=record
            if change:dim['value']=change['value'];dim['value_max']=change['value_max']
            if status!='uncertain':dim['verification_level']='two_pass'
            c.execute('UPDATE fichas SET payload=? WHERE id=?',(json.dumps(current),f['id']))
            c.execute('INSERT OR REPLACE INTO verification_pass2 VALUES(?,?,?,?)',(key,f['id'],i,json.dumps(record)))
            page_f=[json.loads(r[0]) for r in c.execute('SELECT payload FROM fichas WHERE page_id=(SELECT page_id FROM fichas WHERE id=?)',(f['id'],))]
        (PRIVATE/'fichas'/f"p{f['pdf_page']:03}.json").write_text(json.dumps({'fichas':page_f},indent=2),encoding='utf-8')
        print(key,status,flush=True)
    with connect() as c:audits=[(r['id'],json.loads(r['payload'])) for r in c.execute('SELECT id,payload FROM verification_pass2')]
    with (reports/'segunda_pasada.csv').open('w',newline='',encoding='utf-8-sig') as stream:
        writer=csv.writer(stream);writer.writerow(['id_cota','estado_antes','estado_despues','locator','lectura','motivo'])
        for key,r in audits:writer.writerow([key,r['before']['status'],r['outcome'],r['locator'],json.dumps(r.get('read_value')),r['reason']])
    (reports/'segunda_pasada_resumen.json').write_text(json.dumps({'warning':warning,'before':dict(Counter(r['before']['status'] for _,r in audits)),'after':dict(Counter(r['outcome'] for _,r in audits))},indent=2),encoding='utf-8')
    report()

if __name__=='__main__':
    from pathlib import Path
    main()
