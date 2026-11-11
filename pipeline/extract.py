"""Coordinate-preserving heuristics. No inferred measurements or invented translations."""
import re
import unicodedata

# DE evidence and ES/EN discovery labels, not a translation of the source prose.
TERMS = {
 'vivienda': ('Wohnung|Wohnhaus|Wohnen', 'housing'),
 'oficina': ('Büro|Verwaltung', 'office'),
 'educación': ('Schule|Klassenraum|Hochschule|Kindergarten', 'education'),
 'salud': ('Krankenhaus|Klinik|Patient|Pflege', 'health'),
 'comercio': ('Laden|Geschäft|Verkauf', 'retail'),
 'industria': ('Fabrik|Werkstatt|Industrie', 'industry'),
 'deporte': ('Sport|Turnhalle|Schwimm', 'sports'),
 'cultura': ('Museum|Theater|Bibliothek', 'culture'),
 'hostelería': ('Hotel|Restaurant|Gaststätte', 'hospitality'),
 'transporte': ('Bahnhof|Flughafen|Verkehr', 'transport'),
 'agricultura': ('Landwirtschaft|Stall|Scheune', 'agriculture'),
}
SPACES = {
 'dormitorio': ('Schlafzimmer|Schlafraum', 'bedroom'),
 'cocina': ('Küche|Küchen', 'kitchen'),
 'baño': ('Badezimmer|Bad|Toilette|WC', 'bathroom'),
 'aula': ('Klassenraum|Unterrichtsraum', 'classroom'),
 'garaje': ('Garage|Stellplatz', 'garage'),
 'pasillo': ('Flur|Gang|Korridor', 'corridor'),
 'escalera': ('Treppe|Treppen', 'stairs'),
}
EQUIPMENT = {'cama': 'Bett|Betten', 'mesa': 'Tisch|Tische', 'silla': 'Stuhl|Stühle',
             'ascensor': 'Aufzug', 'lavabo': 'Waschbecken', 'armario': 'Schrank|Schränke'}
ACTIVITIES = {'dormir': 'Schlafen', 'cocinar': 'Kochen', 'trabajar': 'Arbeiten',
              'circular': 'Verkehr|Bewegung', 'enseñar': 'Unterricht|Lehren'}

def normalize(text):
    return unicodedata.normalize('NFKC', text).strip()

def matches(pattern, text):
    return bool(re.search(r'\b(?:' + pattern + r')\w*', text, re.I))

def dimensions(text):
    result = []
    pattern = r'(?<![\w.,])(\d{1,4}(?:[.,]\d{1,3})?)\s*(mm|cm|m²|m2|m|°)(?!\w)'
    for match in re.finditer(pattern, text):
        context = text[max(0, match.start()-65):min(len(text), match.end()+65)].replace('\n', ' ')
        result.append({'nombre': 'Medida extraída / extracted measurement',
                       'valor': float(match[1].replace(',', '.')), 'unidad': match[2].replace('m2','m²'),
                       'contexto': context})
    return result

def text_blocks(raw):
    result = []
    for block in raw['blocks']:
        if block.get('type') != 0:
            continue
        spans = [s for line in block['lines'] for s in line['spans']]
        text = normalize('\n'.join(''.join(s['text'] for s in line['spans']) for line in block['lines']))
        if text:
            result.append({'text': text, 'bbox': list(block['bbox']),
                           'size': max(s['size'] for s in spans),
                           'bold': any(s['flags'] & 16 for s in spans)})
    return result

def segment(blocks, width, height):
    # Geometry-aware reading order; keep multiple columns as separate segments when uncertain.
    blocks = sorted(blocks, key=lambda b: (round(b['bbox'][1]/12), b['bbox'][0]))
    sizes = sorted(b['size'] for b in blocks if len(b['text']) > 25)
    body = sizes[len(sizes)//2] if sizes else 10
    headings = [b for b in blocks if len(b['text']) < 140 and
                (b['size'] >= body*1.18 or (b['bold'] and len(b['text']) < 80))
                and not b['text'].strip().isdigit()]
    if not blocks:
        return []
    if not headings:
        return [{'title': blocks[0]['text'].split('\n')[0][:120],
                 'text': '\n\n'.join(b['text'] for b in blocks),
                 'bbox': [0,0,width,height], 'confidence': .42}]
    groups = []
    current = []
    title = headings[0]['text']
    for block in blocks:
        if block in headings and current:
            groups.append((title, current))
            current = []
        if block in headings:
            title = block['text']
        current.append(block)
    if current:
        groups.append((title,current))
    return [{'title': t, 'text': '\n\n'.join(b['text'] for b in group),
             'bbox': [min(b['bbox'][0] for b in group), min(b['bbox'][1] for b in group),
                      max(b['bbox'][2] for b in group), max(b['bbox'][3] for b in group)],
             'confidence': .72 if len(group)>1 else .55} for t,group in groups]

def enrich(section):
    text = section['title'] + '\n' + section['text']
    types = [k for k,(p,_) in TERMS.items() if matches(p,text)]
    spaces = [k for k,(p,_) in SPACES.items() if matches(p,text)]
    # Labels are explicitly marked heuristic; German title is always retained.
    labels_es = types + spaces
    labels_en = [TERMS[k][1] for k in types] + [SPACES[k][1] for k in spaces]
    return dict(title_de=section['title'], title_es=' / '.join(labels_es) or section['title'],
                title_en=' / '.join(labels_en) or section['title'], typology=types[0] if types else 'sin clasificar',
                spaces=spaces, dimensions=dimensions(section['text']),
                activities=[k for k,p in ACTIVITIES.items() if matches(p,text)],
                equipment=[k for k,p in EQUIPMENT.items() if matches(p,text)],
                bbox=section['bbox'], text=section['text'], confidence=section['confidence'],
                needs_review=int(section['confidence'] < .7))

def printed_page(page, blocks):
    label = page.get_label()
    if label and label != str(page.number+1):
        return label
    candidates = [b['text'].strip() for b in blocks
                  if (b['bbox'][1] > page.rect.height*.92 or b['bbox'][3] < page.rect.height*.08)
                  and re.fullmatch(r'\d{1,4}|[ivxlcdm]{1,10}', b['text'].strip(), re.I)]
    return candidates[-1] if candidates else None
