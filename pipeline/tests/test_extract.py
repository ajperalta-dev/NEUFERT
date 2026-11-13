import pymupdf as fitz
from pipeline.extract import dimensions, segment, printed_number, text_blocks

def test_dimensions_preserve_context_and_do_not_guess_units():
    result=dimensions('Corridor width 120 cm. Door 900 mm. Area 12 m². Unknown 75.')
    assert len(result)==3
    assert result[0]['metres']==1.2
    assert result[1]['metres']==.9
    assert result[2]['metres'] is None
    assert 'Corridor width' in result[0]['contexto']

def test_extract_segment_bbox_and_page_number():
    doc=fitz.open();page=doc.new_page(width=600,height=800)
    page.insert_text((40,40),'STAIRS',fontsize=20)
    page.insert_text((40,100),'Clear width 1.20 m. Housing stairs.',fontsize=12)
    page.insert_text((300,780),'42')
    blocks,ocr=text_blocks(page)
    assert not ocr
    assert printed_number(blocks,800)=='42'
    entries=segment(blocks,600,800)
    assert entries[0]['title']=='STAIRS'
    assert '1.20 m' in entries[0]['text']
    assert entries[0]['bbox'][0]>=0

def test_empty_page_is_reviewable():
    assert segment([],600,800)[0]['text']==''
