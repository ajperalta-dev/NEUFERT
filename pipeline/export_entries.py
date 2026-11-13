"""Materialize the requested interchange schema under private data."""
import json
from .config import PRIVATE
from .db import connect
from .search import detail

def export_all():
    target=PRIVATE/'entries'
    target.mkdir(parents=True,exist_ok=True)
    with connect() as con:
        for row in con.execute('SELECT id FROM entries'):
            item=detail(con,row[0])
            tags=lambda kind:[tag['value'] for tag in item['tags'] if tag['kind']==kind]
            result={'id':item['id'],'titulo_original':item['title'],'titulo_de':item['title_de'],'titulo_es':item['title_es'],'titulo_en':item['title_en'],
                    'tipologia_edificio':tags('typology'),'espacios':tags('space'),
                    'dimensiones':[{'nombre':d['name'],'valor':d['value'],'unidad':d['unit'],'contexto':d['context']} for d in item['dimensions']],
                    'usos':tags('use'),'mobiliario':tags('furniture'),'pagina_pdf':item['pagina_pdf'],'pagina_impresa':item['pagina_impresa'],
                    'bbox':item['bbox'],'figuras':[dict(f,bbox=json.loads(f['bbox'])) for f in item['figures']],
                    'confianza':item['confidence'],'requiere_revision':bool(item['review']),'texto':item['text']}
            (target/(item['id']+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':export_all()
