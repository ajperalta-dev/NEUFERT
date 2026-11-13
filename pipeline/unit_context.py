"""Conservative unit declarations from page text and word-coordinate evidence."""
import re
import unicodedata

UNIT = r'(?:mm|cm|m|millimet(?:er|re)s?|centimet(?:er|re)s?|met(?:er|re)s?)'
DECLARATION = re.compile(
    rf'(?i)\b(?:(?:all|alle)\s+)?(?:dimensions?|measurements?|sizes?|values?|units?|ma[eß]e|abmessungen|ma[ßs]angaben|einheiten)'
    rf'\s*(?:\([^)]{{0,20}}\)\s*)?(?:(?:are|is|shown|given|expressed|measured)\s+)?'
    rf'(?:in|:|=)\s*(?P<unit>{UNIT})\b'
)
UNIT_ONLY = re.compile(rf'(?i)\b{UNIT}\b')
UNIT_NORMAL = {
    'mm':'mm','millimeter':'mm','millimeters':'mm','millimetre':'mm','millimetres':'mm',
    'cm':'cm','centimeter':'cm','centimeters':'cm','centimetre':'cm','centimetres':'cm',
    'm':'m','meter':'m','meters':'m','metre':'m','metres':'m',
}

def canonical_unit(value):
    return UNIT_NORMAL.get(value.casefold(), UNIT_NORMAL.get(value.casefold().rstrip('s')))

def _tokens(value):
    return [unicodedata.normalize('NFKC',x).casefold().strip('.,:;()[]{}') for x in re.findall(r"[\w.]+",value,flags=re.UNICODE) if x.strip('.,:;()[]{}')]

def _bbox_for_phrase(words, phrase):
    wanted=_tokens(phrase)
    actual=[_tokens(w[0]) for w in words]
    flat=[]
    for i,parts in enumerate(actual):
        for part in parts:flat.append((part,i))
    for start in range(0,len(flat)-len(wanted)+1):
        if [p for p,_ in flat[start:start+len(wanted)]]==wanted:
            indices=[i for _,i in flat[start:start+len(wanted)]]
            selected=[words[i] for i in sorted(set(indices))]
            return [min(w[1] for w in selected),min(w[2] for w in selected),max(w[3] for w in selected),max(w[4] for w in selected)]
    return None

def declarations(text,words,page_pdf=None):
    lines=text.splitlines()
    expanded=[]
    for i,line in enumerate(lines):
        expanded.append(line.strip())
        # OCR sometimes line-wraps only the final unit after a declarative header.
        if re.search(r'(?i)\b(?:in|are|is|:|=)\s*$',line):
            for following in lines[i+1:i+3]:
                if UNIT_ONLY.fullmatch(following.strip()):
                    expanded.append(line.strip()+' '+following.strip());break
    found=[];seen=set()
    for line in expanded:
        for match in DECLARATION.finditer(line):
            unit=canonical_unit(match.group('unit'))
            citation=match.group(0).strip()
            key=(unit,citation.casefold())
            if key in seen:continue
            seen.add(key)
            bbox=_bbox_for_phrase(words,citation)
            found.append({'unit':unit,'citation':citation,'bbox':bbox,'page_pdf':page_pdf})
    return found

def plausible(d,unit):
    number=max(abs(float(d['value'])),abs(float(d.get('value_max') or d['value'])))
    metres=number*{'mm':.001,'cm':.01,'m':1}[unit]
    semantic=' '.join((d.get('label',''),d.get('context',''))).casefold()
    human=any(x in semantic for x in ('body','human','person','sitting','standing','kneeling','crawling','anthropometr','reach','height of man','man as measure'))
    if human:return .02<=metres<=5
    if any(x in semantic for x in ('door','window','furniture','chair','table','bed','desk','equipment','fixture')):return .02<=metres<=15
    if any(x in semantic for x in ('corridor','passage','hallway','stair','aisle')):return .3<=metres<=30
    if any(x in semantic for x in ('building height','tower','high-rise','storey height','floor-to-floor','mast')):return .1<=metres<=1000
    if any(x in semantic for x in ('room','space','span','floor area','bay')):return .1<=metres<=500
    return .001<=metres<=1000

def infer(d,words,text,dimension_bbox=None,candidates=None,dimension_page=None):
    found=declarations(text,words,dimension_page) if candidates is None else candidates
    if not found:return {'status':'pending','reason':'No explicit unit declaration found in page text/words.'}
    available=[x for x in found if x.get('bbox') is not None]
    units={x['unit'] for x in found}
    chosen=None
    if len(units)==1:
        # If the page repeats a single unit, the nearest declaration can be cited
        # only when it is clearly local; otherwise a sole page-level statement is
        # required to keep the source auditable.
        if len(available)==1:
            chosen=available[0]
        elif len(available)>1 and dimension_page is not None:
            local=[x for x in available if x.get('page_pdf')==dimension_page]
            if len(local)==1:
                chosen=local[0]
            elif dimension_bbox and local:
                ordered=sorted(((_distance(x['bbox'],dimension_bbox),x) for x in local),key=lambda pair:pair[0])
                if ordered[0][0] <= .08 and (len(ordered)==1 or ordered[1][0]-ordered[0][0] >= .04):
                    chosen=ordered[0][1]
            if chosen is None:
                distances=sorted({abs(int(x['page_pdf'])-dimension_page) for x in available if x.get('page_pdf') is not None})
                if distances:
                    nearest=[x for x in available if x.get('page_pdf') is not None and abs(int(x['page_pdf'])-dimension_page)==distances[0]]
                    nearest_pages={x['page_pdf'] for x in nearest}
                    if len(nearest_pages)==1 and len(nearest)==1:
                        chosen=nearest[0]
        if chosen is None:
            reason='Multiple declarations share this unit; no unique local declaration for the figure or section.' if len(available)>1 else 'The unit declaration has no matching word-coordinate bbox.'
            return {'status':'pending','reason':reason,'candidates':[dict(x) for x in found]}
    else:
        return {'status':'pending','reason':'Multiple different unit declarations on the page.','candidates':[dict(x) for x in found]}
    if chosen['unit'] not in ('mm','cm','m') or not plausible(d,chosen['unit']):
        return {'status':'rejected','reason':'The context unit fails the plausibility range for this dimension.',**chosen}
    return {'status':'inferred','unit':chosen['unit'],'unit_source':'page_context','unit_citation':chosen['citation'],
            'unit_bbox':chosen['bbox'],'unit_page_pdf':chosen.get('page_pdf')}

def _distance(a,b):
    if not b:return 0.
    ax=(a[0]+a[2])/2;ay=(a[1]+a[3])/2;bx=(b[0]+b[2])/2;by=(b[1]+b[3])/2
    return ((ax-bx)**2+(ay-by)**2)**.5
