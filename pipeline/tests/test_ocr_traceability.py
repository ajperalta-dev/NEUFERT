from pipeline.ocr_traceability import source_span

def test_span_preserves_original_decimal_comma_and_spacing():
    assert source_span('1.20 m','Clearance 1,20  m at door')==('1,20  m','format_normalized')

def test_no_invented_numeric_span():
    source='Door height 12.0 m'
    assert source_span('1.20 m',source)==(source,'full_page_fallback')

def test_missing_span_keeps_full_original_ocr():
    assert source_span('', 'No readable dimension here')==('No readable dimension here','full_page_fallback')
