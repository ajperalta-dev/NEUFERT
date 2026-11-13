"""Isolated, resumable 39–48 pilot; never updates production fichas or Luna files."""
import argparse
import csv
import hashlib
import html
import json
import logging
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from threading import Lock

import httpx
import pymupdf as fitz
from pydantic import BaseModel, Field
from typing import Literal

from .config import PRIVATE, SOURCE
from .db import connect
from .verify_pass2 import Reading, Location, locate, crop, decide
from .vision_fichas import VisionProvider, validated

RUN = 'sol61-pilot-39-48'
RATE_SOURCE = 'https://developers.openai.com/api/docs/models/'
RATES = {'gpt-6-luna': (.1, .5, .01), 'gpt-6.1-sol': (2., 10., .1)}
LOCK = Lock()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def atomic(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def production_digest():
    with connect() as con:
        h = hashlib.sha256()
        for table, order in [('fichas', 'id'), ('verification_pass2', 'id'), ('embeddings', 'rowid')]:
            for row in con.execute(f'SELECT * FROM {table} ORDER BY {order}'):
                h.update(repr(tuple(row)).encode())
        return h.hexdigest()


def freeze(root):
    manifest_path = root / 'manifest.json'
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding='utf-8'))
    with connect() as con:
        baseline = []
        for r in con.execute('SELECT id,ficha_id,dimension_index,payload FROM verification_pass2 ORDER BY id'):
            a = json.loads(r['payload'])
            f = json.loads(con.execute('SELECT payload FROM fichas WHERE id=?', (r['ficha_id'],)).fetchone()[0])
            if 39 <= f['pdf_page'] <= 48:
                baseline.append({'key': r['id'], 'ficha_id': r['ficha_id'], 'index': r['dimension_index'],
                                 'pdf_page': f['pdf_page'], 'chapter': f['chapter'], 'luna': a,
                                 'dimension': a['before']})
    if len(baseline) != 62 or Counter(r['dimension']['status'] for r in baseline) != {'uncertain': 61, 'corrected': 1}:
        raise ValueError('Expected the original 62-dimension pilot, not current pending states')
    frozen = root / 'luna-frozen'
    frozen.mkdir()
    files = [PRIVATE / 'vision-usage-pass2.jsonl']
    files += list((PRIVATE / 'reports').glob('segunda_pasada*'))
    files += [PRIVATE / b['luna']['crop_path'] for b in baseline if b['luna'].get('crop_path')]
    files += [PRIVATE / 'base-package/words' / f'p{p:03}.json' for p in {b['pdf_page'] for b in baseline}]
    hashes = {}
    for path in files:
        rel = path.relative_to(PRIVATE)
        dest = frozen / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        hashes[str(rel)] = digest(path.read_bytes())
    provenance = json.loads((PRIVATE / 'reports/ocr-provenance.json').read_text(encoding='utf-8'))
    for b in baseline:
        b['model_candidate'] = provenance.get(b['key'], {}).get('model_candidate')
    atomic(root / 'baseline.json', baseline)
    manifest = {'run_id': RUN, 'model': 'gpt-6.1-sol', 'created': datetime.now(timezone.utc).isoformat(),
                'production_digest': production_digest(), 'luna_files': hashes,
                'source_sha256': digest(SOURCE.read_bytes()),
                'decision_code_sha256': digest(Path(__file__).with_name('verify_pass2.py').read_bytes()),
                'input_sha256': digest((root / 'baseline.json').read_bytes()), 'rates_per_million': RATES,
                'rate_sources': {m: RATE_SOURCE + m for m in RATES},
                'comparison_note': 'Same 62 first-pass candidates, locator algorithm, blind prompts and decision function. Sol independently locates and reads; Luna original results remain frozen.'}
    atomic(manifest_path, manifest)
    return manifest


class AuditProvider(VisionProvider):
    def __init__(self, root, key, stage):
        super().__init__()
        self.root, self.key_id, self.stage = root, key, stage

    def generate(self, image, prompt):
        result, usage = super().generate(image, prompt)
        entry = {'key': self.key_id, 'stage': self.stage, 'model': self.model, 'usage': usage,
                 'time': datetime.now(timezone.utc).isoformat()}
        with LOCK, (self.root / 'calls.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(entry) + '\n')
        return result, usage


def redact(text):
    return re.sub(r'\d+(?:[.,]\d+)?', '[redacted]', text)


def tiles(root, number):
    """Identical contact sheet to Luna, generated from its cached source tiles."""
    target = root / f'p{number:03}_tiles.png'
    if target.exists():
        return target
    from PIL import Image, ImageDraw
    sheet = Image.new('RGB', (2400, 3300), 'white')
    with fitz.open(SOURCE) as document:
        page = document[number - 1]
        for n in range(9):
            source = PRIVATE / 'crops' / f'p{number:03}_tile{n}.png'
            if source.exists():
                im = Image.open(source).copy()
            else:
                x, y = n % 3, n // 3
                b = [max(0, x / 3 - .025), max(0, y / 3 - .025), min(1, (x + 1) / 3 + .025), min(1, (y + 1) / 3 + .025)]
                rect = page.rect
                pix = page.get_pixmap(matrix=fitz.Matrix(300 / 72, 300 / 72),
                    clip=fitz.Rect(b[0]*rect.width, b[1]*rect.height, b[2]*rect.width, b[3]*rect.height), colorspace=fitz.csGRAY)
                im = Image.frombytes('L', [pix.width, pix.height], pix.samples)
            im.thumbnail((790, 1060))
            xy = (n % 3 * 800, n // 3 * 1100)
            sheet.paste(im, (xy[0], xy[1] + 30))
            ImageDraw.Draw(sheet).text(xy, str(n), fill='black')
    sheet.save(target)
    return target


def save_result(root, key, value):
    with sqlite3.connect(root / 'run.sqlite3', timeout=60) as con:
        con.execute('INSERT OR REPLACE INTO results VALUES(?,?)', (key, json.dumps(value)))


def verify(root, item):
    d, number, key = item['dimension'], item['pdf_page'], item['key']
    words = json.loads((root / 'luna-frozen/base-package/words' / f'p{number:03}.json').read_text(encoding='utf-8'))['words']
    method, bbox = locate(words, d)
    result = {'model': 'gpt-6.1-sol', 'before': d, 'pdf_page': number, 'locator': method,
              'timestamp': datetime.now(timezone.utc).isoformat(), 'key': key}
    try:
        if bbox is None:
            provider = AuditProvider(root, key, 'locate')
            loc, _ = validated(provider, (root / f'p{number:03}_tiles.png').read_bytes(),
                'Locate the dimension by label/context ONLY. Do not guess. Return tile index 0-8 and normalized bbox within that tile. Label: '
                + redact(d['label']) + ' Context: ' + redact(d['context']) + ' Schema: ' + json.dumps(Location.model_json_schema()), Location)
            if not loc.found:
                result.update(outcome='uncertain', reason='Dimension not located in tiles', failure_stage='locate')
                save_result(root, key, result)
                return result
            x, y = loc.tile % 3, loc.tile // 3
            tb = [max(0, x/3-.025), max(0, y/3-.025), min(1, (x+1)/3+.025), min(1, (y+1)/3+.025)]
            bbox = [tb[0]+loc.bbox[0]*(tb[2]-tb[0]), tb[1]+loc.bbox[1]*(tb[3]-tb[1]),
                    tb[0]+loc.bbox[2]*(tb[2]-tb[0]), tb[1]+loc.bbox[3]*(tb[3]-tb[1])]
        if not all(0 <= v <= 1 for v in bbox) or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            raise ValueError('Invalid locator bbox')
        target = root / 'crops' / f'p{number:03}_{item["ficha_id"]}_{item["index"]}.png'
        with fitz.open(SOURCE) as pdf:
            actual = crop(pdf[number-1], bbox, target)
        result.update(bbox=bbox, crop_bbox=actual, crop_path=str(target.relative_to(root)))
        provider = AuditProvider(root, key, 'read')
        reading, _ = validated(provider, target.read_bytes(),
            'Read ONLY the explicitly printed number/range and unit corresponding to label ' + redact(d['label'])
            + '; context ' + redact(d['context']) + '. No calculations or inferred values. If ambiguous set unreadable=true. Schema: '
            + json.dumps(Reading.model_json_schema()), Reading)
        status, reason, change = decide(d, reading, item.get('model_candidate'))
        result.update(read_value=reading.model_dump(), outcome=status, reason=reason,
                      proposed_change=change if change else None)
    except httpx.HTTPStatusError as error:
        # No partial "uncertain" results for auth/quota/provider failures.
        if error.response.status_code in (401, 403, 429):
            raise
        raise RuntimeError(f'Provider HTTP {error.response.status_code} for {key}') from None
    except (httpx.NetworkError, httpx.TimeoutException):
        raise
    except Exception as error:
        result.update(outcome='uncertain', reason=str(error), failure_stage='locate' if not result.get('crop_path') else 'read', error=True)
    save_result(root, key, result)
    logging.info('%s %s', key, result['outcome'])
    return result


class Diagnostic(BaseModel):
    id: str
    target_located: bool
    target_legible: bool
    non_measure: bool
    explicit_numeric_measure: bool
    printed_evidence: str
    reason: str
    confidence: float = Field(ge=0, le=1)


class Diagnostics(BaseModel):
    items: list[Diagnostic]


def cost(entries, model):
    values = [e.get('usage', {}) for e in entries]
    inputs = sum(e.get('prompt_tokens', 0) for e in values)
    outputs = sum(e.get('completion_tokens', 0) for e in values)
    cached = sum(e.get('prompt_tokens_details', {}).get('cached_tokens', 0) for e in values)
    rate_in, rate_out, rate_cached = RATES[model]
    return {'responses': len(entries), 'input_tokens': inputs, 'output_tokens': outputs, 'cached_input_tokens': cached,
            'usd_standard_uncached': (inputs * rate_in + outputs * rate_out) / 1e6,
            'usd_with_observed_cache': ((inputs-cached)*rate_in + cached*rate_cached + outputs*rate_out) / 1e6}


def collect(root):
    with sqlite3.connect(root / 'run.sqlite3') as con:
        return {k: json.loads(p) for k, p in con.execute('SELECT id,payload FROM results')}


def diagnose(root, baseline, sol):
    """Additional Sol-only analysis of both models' crops, not part of their blind pass."""
    path = root / 'diagnostics.json'
    done = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    pending = []
    for item in baseline:
        for model, record in [('luna', item['luna']), ('sol', sol[item['key']])]:
            key = model + ':' + item['key']
            if record['outcome'] != 'uncertain' or not record.get('crop_path') or key in done:
                continue
            image = (root / 'luna-frozen' / record['crop_path']) if model == 'luna' else root / record['crop_path']
            pending.append((key, item, image))
    # One call per crop: no image compression or contact-sheet ambiguity for this diagnosis.
    def one(entry):
        key, item, image = entry
        provider = AuditProvider(root, key, 'diagnostic')
        prompt = ('Classify this located reference element, not the entire page. Do NOT solve formulas, convert ratios to decimals, '
                  'or invent a missing measurement. Determine whether the TARGET is merely a mathematical symbol/formula, fraction or '
                  'proportion WITHOUT an explicitly printed numeric measurement. A printed number or dimensionless numeric ratio '
                  'is NOT non_measure merely because no physical unit is visible. If the crop shows only a page number, figure number, '
                  'or unrelated drawing, set target_located=false instead of classifying the requested target as non_measure. '
                  'Use target_legible=false when the localized target is too blurred to read. Only set non_measure=true '
                  'when the requested target itself is localized and legible. Quote visible evidence, explain uncertainty. '
                  'No candidate values are supplied. Return one item with id ' + key + '. Label: ' + redact(item['dimension']['label'])
                  + '; context: ' + redact(item['dimension']['context']) + '; schema: ' + json.dumps(Diagnostics.model_json_schema()))
        data, _ = validated(provider, image.read_bytes(), prompt, Diagnostics)
        if len(data.items) != 1 or data.items[0].id != key:
            raise ValueError('Diagnostic target mismatch')
        return key, data.items[0].model_dump()
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(one, e) for e in pending]
        for future in as_completed(futures):
            key, value = future.result()
            done[key] = value
            atomic(path, done)
            logging.info('Diagnostic %s', key)
    return done


def numeric_literals(text):
    normalized = re.sub(r'(?<=\d)\s*[-–]\s*(?=\d)', ' ', text.replace(',', '.'))
    return [float(v) for v in re.findall(r'(?<![\w.])-?\d+(?:\.\d+)?', normalized)]


def cause(record, diagnostic, model_candidate=None):
    if not record.get('crop_path') or record.get('failure_stage') == 'locate' or (diagnostic and not diagnostic.get('target_located', True)):
        return 'a'
    if diagnostic and not diagnostic.get('target_legible', True):
        return 'b'
    if diagnostic and diagnostic['non_measure'] and not diagnostic['explicit_numeric_measure'] and diagnostic['confidence'] >= .9 and diagnostic['printed_evidence'].strip():
        return 'd'
    if record.get('read_value', {}).get('unreadable') or not record.get('read_value'):
        return 'b'
    # A number can be legible while its required physical unit cannot be read.
    # Do not misreport such cases as two disagreeing numeric values.
    if not record['read_value'].get('unit', '').strip() and record.get('before', {}).get('unit') in ('mm', 'cm', 'm'):
        d = record['before']
        observed = numeric_literals(record['read_value'].get('printed', ''))
        candidates = [[d['value']] + ([d['value_max']] if d.get('value_max') is not None else [])]
        original = numeric_literals(model_candidate or '')
        if 1 <= len(original) <= 2:
            candidates.append(original)
        if any(len(observed) == len(values) and all(math.isclose(x,y,rel_tol=1e-6,abs_tol=1e-8) for x,y in zip(observed,values)) for values in candidates):
            return 'b'
    return 'c'


def report_comparison(root, baseline, sol, diagnostics):
    luna_usage = [json.loads(line) for line in (root / 'luna-frozen/vision-usage-pass2.jsonl').read_text().splitlines()]
    sol_usage = [json.loads(line) for line in (PRIVATE / f'vision-usage-pass2-{RUN}.jsonl').read_text().splitlines()]
    calls_path = root / 'calls.jsonl'
    detailed = [json.loads(line) for line in calls_path.read_text().splitlines()] if calls_path.exists() else []
    sol_verification = [c for c in detailed if c['stage'] != 'diagnostic']
    diagnostic_usage = [c for c in detailed if c['stage'] == 'diagnostic']
    result, details = {}, []
    for name, model, usage in [('luna', 'gpt-6-luna', luna_usage), ('sol', 'gpt-6.1-sol', sol_verification)]:
        transitions, causes = Counter(), Counter()
        number_matches_without_unit = 0
        for item in baseline:
            record = item['luna'] if name == 'luna' else sol[item['key']]
            transitions[item['dimension']['status'] + ' -> ' + record['outcome']] += 1
            category = cause(record, diagnostics.get(name + ':' + item['key']), item.get('model_candidate')) if record['outcome'] == 'uncertain' else None
            if category:
                causes[category] += 1
            reading = record.get('read_value') or {}
            numeric_literal = reading.get('printed', '').strip().replace(',', '.')
            # Descriptive metric only: does not infer units or change any decision.
            literal_match = (category == 'b' and not reading.get('unreadable')
                             and not reading.get('unit', '').strip()
                             and re.fullmatch(r'\d+(?:\.\d+)?', numeric_literal) is not None
                             and float(numeric_literal) == item['dimension']['value']
                             and item['dimension'].get('value_max') is None)
            number_matches_without_unit += bool(literal_match)
            details.append({'run': name, 'key': item['key'], 'pdf_page': item['pdf_page'], 'label': item['dimension']['label'],
                            'before': item['dimension']['status'], 'after': record['outcome'], 'cause': category,
                            'reading': record.get('read_value'), 'reason': record['reason'],
                            'diagnostic': diagnostics.get(name + ':' + item['key']), 'crop_path': record.get('crop_path'),
                            'same_literal_number_unit_unconfirmed': bool(literal_match)})
        result[name] = {'model': model, 'dimensions': len(baseline), 'transitions': dict(transitions),
                        'uncertain_causes': dict(causes), 'same_literal_number_unit_unconfirmed': number_matches_without_unit,
                        'cost': cost(usage, model)}
    # Freeze first-pass population to avoid counting Luna's subsequent status changes.
    old = sqlite3.connect(PRIVATE / 'before-pass2.sqlite3')
    population = []
    for payload, in old.execute('SELECT payload FROM fichas'):
        f = json.loads(payload)
        population += [(f['pdf_page'], d) for d in f['dimensions'] if d['status'] in ('uncertain', 'corrected')]
    old.close()
    methods = Counter()
    words_cache = {}
    for number, d in population:
        if number not in words_cache:
            words_cache[number] = json.loads((PRIVATE / 'base-package/words' / f'p{number:03}.json').read_text(encoding='utf-8'))['words']
        methods[locate(words_cache[number], d)[0]] += 1
    estimates = {}
    for name in result:
        pilot_cost = result[name]['cost']['usd_standard_uncached']
        estimates[name] = {'full_queue_dimensions': len(population), 'remaining_after_pilot': len(population)-len(baseline),
                           'full_usd_linear': pilot_cost/len(baseline)*len(population),
                           'remaining_usd_linear': pilot_cost/len(baseline)*(len(population)-len(baseline)),
                           'sensitivity_minus30_plus50': [pilot_cost/len(baseline)*len(population)*.7, pilot_cost/len(baseline)*len(population)*1.5]}
    summary = {'runs': result, 'full_run_estimates': estimates, 'full_queue_locator_counts': dict(methods),
               'diagnostic_analysis_cost': cost(diagnostic_usage, 'gpt-6.1-sol'),
               'all_sol_responses_cost': cost(sol_usage, 'gpt-6.1-sol'),
               'rule_proposal': 'Proponer not_a_dimension solo si el objetivo está localizado y es legible, se observa un símbolo/fórmula o una fracción/proporción SIN medida numérica impresa, existe evidencia visual citada y la confianza es al menos 0,90. La falta de unidad, una lectura ilegible, una razón numérica impresa válida o un desacuerdo no bastan. Una aplicación futura exigiría confirmación independiente; añadir classification=not_a_dimension e historial, conservando value/value_max/unit/ocr_raw y el estado anterior. En este experimento solo se propone: no se reclasifica ninguna ficha.',
               'notes': ['Production fichas, Luna results, vectors and original crops remain unchanged.',
                         'Diagnosis of both runs uses Sol; it is an automatic attribution, not independent ground truth. Diagnostic cost is separate from pilot verification costs.',
                         'Cause b includes incomplete readings where the number is visible but the required physical unit is not printed/readable. Cause c covers remaining value/range/unit disagreements. Missing units alone never imply a non-dimension.',
                         'Full costs extrapolate a 62-item pilot dominated by PDF 41; sensitivity bounds are scenarios, not statistical confidence intervals. No full run executed.',
                         'Reported costs are token-based estimates, not invoices; no regional surcharge or failed requests without usage are included.'],
               'details': details}
    atomic(root / 'comparison.json', summary)
    with (root / 'comparison.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=['run','key','pdf_page','label','before','after','cause','reading','reason','diagnostic','crop_path','same_literal_number_unit_unconfirmed'])
        writer.writeheader()
        for row in details:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v for k,v in row.items()})
    comparison_rows = ''
    for name, r in result.items():
        t = r['transitions']
        comparison_rows += f'<tr><td>{r["model"]}</td><td>{t.get("uncertain -> verified",0)}</td><td>{t.get("uncertain -> corrected",0)}</td><td>{t.get("uncertain -> uncertain",0)}</td><td>{t.get("corrected -> corrected",0)}</td><td>{t.get("corrected -> uncertain",0)}</td><td>${r["cost"]["usd_standard_uncached"]:.6f}</td><td>${r["cost"]["usd_with_observed_cache"]:.6f}</td></tr>'
    labels = {'a':'No localizada','b':'Lectura ilegible o incompleta (incluye unidad no visible)','c':'Lectura distinta de ambos valores / unidad incompatible','d':'Propuesta: elemento sin medida numérica impresa'}
    cause_rows = ''.join(f'<tr><td>{k}: {v}</td><td>{result["luna"]["uncertain_causes"].get(k,0)}</td><td>{result["sol"]["uncertain_causes"].get(k,0)}</td></tr>' for k,v in labels.items())
    estimate_rows = ''.join(f'<tr><td>{result[n]["model"]}</td><td>${e["full_usd_linear"]:.3f}</td><td>${e["remaining_usd_linear"]:.3f}</td><td>${e["sensitivity_minus30_plus50"][0]:.3f}–${e["sensitivity_minus30_plus50"][1]:.3f}</td></tr>' for n,e in estimates.items())
    panels = ''
    for d in details:
        if d['cause'] is None:
            continue
        prefix = 'luna-frozen/' if d['run']=='luna' else ''
        image = '<img loading="lazy" src="'+html.escape(prefix+d['crop_path'].replace('\\','/'))+'" alt="Recorte PDF '+str(d['pdf_page'])+'">' if d['crop_path'] else ''
        panels += '<details><summary>'+html.escape(f'{d["run"]} · PDF {d["pdf_page"]} · {d["label"]} · causa {d["cause"]}')+'</summary>'+image+'<pre>'+html.escape(json.dumps(d, ensure_ascii=False, indent=2))+'</pre></details>'
    markup = '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Neufert — Luna vs Sol 6.1</title><style>body{font:16px/1.5 system-ui;max-width:1200px;margin:40px auto;padding:0 20px;color:#151515}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:12px;border-bottom:1px solid #ddd;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere}img{max-width:100%;max-height:900px}details{margin:20px 0}summary{cursor:pointer}.scroll{overflow:auto}</style>'
    markup += '<h1>Piloto: Luna vs Sol 6.1</h1><p>PDF 39–48 · 62 entradas originales: 61 inciertas y 1 corregida. Corridas independientes; no se ha aplicado Sol a las fichas.</p><h2>Transiciones y coste:</h2><div class="scroll"><table><tr><th>Modelo</th><th>Incierta → verified</th><th>Incierta → corrected</th><th>Sigue incierta</th><th>Corrected confirmada</th><th>Corrected → incierta</th><th>Coste estándar USD</th><th>Con caché observada USD</th></tr>'+comparison_rows+'</table></div>'
    markup += '<h2>Causas de incertidumbre:</h2><table><tr><th>Causa</th><th>Luna</th><th>Sol 6.1</th></tr>'+cause_rows+'</table><p>La atribución semántica d usa Sol y es una propuesta de clasificación. La causa b incluye una lectura incompleta cuando la cifra es legible pero su unidad física no está visible; c recoge los desacuerdos restantes.</p>'
    markup += '<p>Dentro de b, la cifra literal coincide con la actual pero falta una unidad confirmada en '+str(result['luna']['same_literal_number_unit_unconfirmed'])+' cotas de Luna y '+str(result['sol']['same_literal_number_unit_unconfirmed'])+' de Sol. No son discrepancias numéricas y no se ha supuesto ninguna unidad.</p>'
    markup += '<h2>Propuesta not_a_dimension:</h2><p>'+html.escape(summary['rule_proposal'])+'</p><h2>Estimación para todo el libro:</h2><p>Cola inicial: '+str(len(population))+' cotas; resto tras el piloto: '+str(len(population)-len(baseline))+'. Sensibilidad orientativa −30% / +50%; muestra concentrada en PDF 41.</p><table><tr><th>Modelo</th><th>Cola completa</th><th>Solo resto</th><th>Sensibilidad cola completa</th></tr>'+estimate_rows+'</table>'
    markup += '<p>El análisis adicional de causas cuesta $'+f'{summary["diagnostic_analysis_cost"]["usd_standard_uncached"]:.6f}'+' y se separa de las corridas de verificación.</p><p>Tarifas estándar por millón, entrada/salida: Luna $0.10/$0.50; Sol $2/$10. <a href="https://developers.openai.com/api/docs/models/gpt-6.1-sol">Tarifas oficiales Sol</a> · <a href="https://developers.openai.com/api/docs/models/gpt-6-luna">Luna</a>.</p><ul>'+''.join('<li>'+html.escape(n)+'</li>' for n in summary['notes'])+'</ul><h2>Evidencia por cota:</h2>'+panels
    (root / 'comparison.html').write_text(markup, encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', default='.env')
    parser.add_argument('--workers', type=int, default=4, choices=range(1,5))
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    for line in Path(args.env_file).read_text(encoding='utf-8-sig').splitlines():
        k, sep, v = line.partition('=')
        if sep and k.strip() in ('OPENAI_API_KEY','NEUFERT_VISION_URL','NEUFERT_VERIFY_MODEL'):
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    model = os.getenv('NEUFERT_VERIFY_MODEL', 'gpt-6.1-sol')
    if model != 'gpt-6.1-sol':
        parser.error('This isolated comparison requires NEUFERT_VERIFY_MODEL=gpt-6.1-sol')
    root = PRIVATE / 'pass2-runs' / RUN
    if args.dry_run:
        with connect() as con:
            count = con.execute('SELECT count(*) FROM verification_pass2').fetchone()[0]
        print(json.dumps({'pilot_dimensions': count, 'model': model, 'full_run': False, 'api_calls': 0}))
        return
    root.mkdir(parents=True, exist_ok=True)
    (root / 'crops').mkdir(exist_ok=True)
    manifest = freeze(root)
    baseline = json.loads((root / 'baseline.json').read_text(encoding='utf-8'))
    if digest((root / 'baseline.json').read_bytes()) != manifest['input_sha256'] or len(baseline) != 62 or any(not 39 <= r['pdf_page'] <= 48 for r in baseline):
        raise RuntimeError('Frozen pilot input changed or exceeded authorized scope')
    if production_digest() != manifest['production_digest']:
        raise RuntimeError('Production baseline changed; refuse to silently mix experiments')
    os.environ['NEUFERT_VISION_MODEL'] = model
    os.environ['NEUFERT_VISION_USAGE_FILE'] = f'vision-usage-pass2-{RUN}.jsonl'
    with sqlite3.connect(root / 'run.sqlite3') as con:
        con.execute('CREATE TABLE IF NOT EXISTS results(id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    done = collect(root)
    pending = [item for item in baseline if item['key'] not in done or done[item['key']].get('error')]
    for number in sorted({item['pdf_page'] for item in pending}):
        tiles(root, number)
    # Warm-up one item to fail immediately if the model is inaccessible.
    if pending:
        verify(root, pending.pop(0))
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(verify, root, item) for item in pending]
        try:
            for future in as_completed(futures):
                future.result()
        except Exception:
            for future in futures:
                future.cancel()
            raise
    sol = collect(root)
    if len(sol) != len(baseline):
        raise ValueError('Pilot incomplete')
    diagnostics = diagnose(root, baseline, sol)
    summary = report_comparison(root, baseline, sol, diagnostics)
    unchanged = production_digest() == manifest['production_digest'] and all(digest((PRIVATE / path).read_bytes()) == value for path,value in manifest['luna_files'].items())
    atomic(root / 'integrity.json', {'production_and_luna_unchanged': unchanged, 'completed_dimensions': len(sol)})
    if not unchanged:
        raise RuntimeError('Production or Luna changed during comparison')
    print(json.dumps({k:v for k,v in summary.items() if k != 'details'}, ensure_ascii=True))


if __name__ == '__main__':
    main()
