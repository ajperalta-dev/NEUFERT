import json,csv,html
from collections import Counter,defaultdict
from .config import PRIVATE
from .db import connect
from .vision_fichas import report
from .page_embeddings import build
from .ocr_traceability import ficha_text

def finalize():
 out=PRIVATE/'reports';counts=defaultdict(Counter);examples=[];entities=[]
 with connect() as c:
  rows=c.execute('SELECT v.id,v.ficha_id,v.payload,f.payload AS ficha FROM verification_pass2 v JOIN fichas f ON f.id=v.ficha_id').fetchall()
  for r in rows:
   a=json.loads(r['payload']);f=json.loads(r['ficha']);a.update(id_cota=r['id'],pdf_page=f['pdf_page'],chapter=f['chapter']);examples.append(a)
   counts[f['chapter']][a['before']['status']+' -> '+a['outcome']]+=1
  for fid in {r['ficha_id'] for r in rows}:
   f=c.execute('SELECT payload FROM fichas WHERE id=?',(fid,)).fetchone()[0];entities.append(('ficha',fid,ficha_text(f)))
 build(entities)
 with (out/'segunda_pasada.csv').open('w',newline='',encoding='utf-8-sig') as stream:
  writer=csv.writer(stream);writer.writerow(['id_cota','pdf_page','chapter','before','after','locator','read_value','reason'])
  for a in examples:writer.writerow([a['id_cota'],a['pdf_page'],a['chapter'],a['before']['status'],a['outcome'],a['locator'],json.dumps(a.get('read_value')),a['reason']])
 summary={'before':dict(Counter(a['before']['status'] for a in examples)),'after':dict(Counter(a['outcome'] for a in examples)),'chapters':{k:dict(v) for k,v in counts.items()},'warnings':sorted({a['warning'] for a in examples if a.get('warning')})}
 (out/'segunda_pasada_resumen.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
 panels=''
 available=[a for a in examples if a.get('crop_path')]
 chosen=[]
 for status in ('verified','corrected','uncertain'):
  candidate=next((a for a in available if a['outcome']==status),None)
  if candidate:chosen.append(candidate)
 chosen.extend(a for a in available if a not in chosen)
 for a in chosen[:5]:
  panels+='<section><h2>'+html.escape(a['id_cota'])+'</h2><img style="max-width:100%" src="../'+html.escape(a['crop_path'].replace('\\','/'))+'"><p>'+html.escape(a['before']['status']+' → '+a['outcome']+': '+a['reason'])+'</p></section>'
 (out/'segunda_pasada.html').write_text('<meta charset="utf-8"><title>Segunda pasada</title><h1>Segunda pasada: piloto PDF 39–48</h1><p>Validación automática por IA, no revisión humana.</p><pre>'+html.escape(json.dumps(summary,indent=2))+'</pre>'+panels,encoding='utf-8')
 path=out/'segunda_pasada.html'
 table='<table><tr><th>Estado</th><th>Antes</th><th>Después</th></tr>'+''.join('<tr><td>'+state+'</td><td>'+str(summary['before'].get(state,0))+'</td><td>'+str(summary['after'].get(state,0))+'</td></tr>' for state in ('uncertain','corrected','verified'))+'</table>'
 path.write_text(path.read_text(encoding='utf-8').replace('<pre>',table+'<pre>',1),encoding='utf-8')
 report();print(json.dumps(summary))
if __name__=='__main__':finalize()
