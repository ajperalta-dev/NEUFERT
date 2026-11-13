import re
import pymupdf as fitz
from PIL import Image

def text_blocks(page, ocr_language='deu'):
    plain = page.get_text()
    ocr = len(re.sub(r'\W','',plain)) < 30
    textpage = page.get_textpage_ocr(language=ocr_language, dpi=300, full=True) if ocr else None
    data = page.get_text('dict', textpage=textpage)
    blocks=[]
    for block in data['blocks']:
        if block['type'] != 0:
            continue
        spans=[span for line in block['lines'] for span in line['spans']]
        text='\n'.join(' '.join(span['text'] for span in line['spans']) for line in block['lines']).strip()
        if text:
            blocks.append({'text':text, 'bbox':list(block['bbox']), 'size':max(s['size'] for s in spans)})
    return blocks, ocr

def printed_number(blocks, height):
    candidates=[]
    for block in blocks:
        if block['bbox'][1] > height*.89 and re.fullmatch(r'\d{1,4}|[ivxlcdm]{1,8}',block['text'].strip(),re.I):
            candidates.append(block['text'].strip())
    return candidates[-1] if candidates else None

def segment(blocks, width, height):
    """Page-local section boundaries; preserve exact block membership/bboxes.

    OCR fonts often have no hierarchy: use top-page title, then conservative
    column-aware chunks. No invented section titles when OCR is missing.
    """
    usable=[b for b in blocks if not (b['bbox'][1]>height*.93 and len(b['text'])<12)]
    if not usable:
        return [{'title':'[Sin texto / No text]', 'text':'', 'bbox':[0,0,width,height]}]
    headings=[b for b in usable if b['bbox'][1]<height*.22 and 3<len(b['text'])<110 and len(b['text'].splitlines())<=3]
    title = max(headings, key=lambda b:(b['text'].isupper(), b['size']), default=usable[0])['text'].replace('\n',' ')[:140]
    # One page = one section entry for scanned reference sheets. Exact blocks
    # retained for future finer subdivision; avoids breaking diagram/caption pairs.
    return [{'title':title, 'text':'\n'.join(b['text'] for b in usable),
             'bbox':[min(b['bbox'][0] for b in usable),min(b['bbox'][1] for b in usable),
                     max(b['bbox'][2] for b in usable),max(b['bbox'][3] for b in usable)]}]

def dimensions(text):
    result=[]
    # Only explicitly printed units. Bare numbers are not assigned units.
    pattern=r'(?<![\w.])(?P<value>\d{1,5}(?:[.,]\d{1,4})?)\s*(?P<unit>mm|cm|m²|m2|m|°)(?!\w)'
    for match in re.finditer(pattern,text):
        value=float(match['value'].replace(',','.'))
        unit=match['unit']
        context=text[max(0,match.start()-65):min(len(text),match.end()+65)].replace('\n',' ')
        result.append({'nombre':'Medida extraída', 'valor':value,'unidad':unit,'contexto':context,
                       'metres':value*{'mm':.001,'cm':.01,'m':1}[unit] if unit in ('mm','cm','m') else None})
    return result

def render(page, target, dpi=150, bbox=None):
    pix=page.get_pixmap(dpi=dpi, clip=fitz.Rect(bbox) if bbox else None, alpha=False)
    image=Image.frombytes('RGB',[pix.width,pix.height],pix.samples)
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary=target.with_suffix('.tmp')
    image.save(temporary,format='WEBP',quality=85)
    temporary.replace(target)

def figure_boxes(page):
    rects=[]
    for item in page.get_image_info():
        rect=fitz.Rect(item['bbox']) & page.rect
        if rect.width>30 and rect.height>30 and rect.get_area()<page.rect.get_area()*.85:
            rects.append((list(rect),'embedded-image'))
    if not rects:
        # A scanned page is one raster. Detect whitespace-separated graphic
        # regions using connected ink runs on a low-resolution raster, excluding
        # OCR text boxes. Each candidate remains explicitly heuristic.
        import numpy as np
        pix=page.get_pixmap(matrix=fitz.Matrix(1,1),colorspace=fitz.csGRAY)
        arr=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width).copy()
        for b in page.get_text('blocks'):
            x0,y0,x1,y1=map(int,b[:4])
            arr[max(0,y0):min(pix.height,y1+1),max(0,x0):min(pix.width,x1+1)]=255
        from scipy.ndimage import binary_dilation, label, find_objects
        ink=arr<150
        connected=binary_dilation(ink,structure=np.ones((9,9)))
        labels,count=label(connected)
        for region in find_objects(labels):
            if region is None: continue
            ys,xs=region
            w,h=xs.stop-xs.start,ys.stop-ys.start
            if w>65 and h>45 and w*h<page.rect.get_area()*.65 and ink[region].sum()>150:
                rects.append(([max(0,xs.start-8),max(0,ys.start-8),min(page.rect.width,xs.stop+8),min(page.rect.height,ys.stop+8)],'raster-region-review'))
    return rects[:24]
