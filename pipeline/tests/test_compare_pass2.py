import pytest
from pipeline.compare_pass2 import cause, cost, RATES


def test_causes_distinguish_wrong_crop_from_non_measure():
    record = {'crop_path': 'crop.png', 'read_value': {'unreadable': False}}
    diagnostic = {'target_located': True, 'target_legible': True, 'non_measure': True,
                  'explicit_numeric_measure': False, 'confidence': .99, 'printed_evidence': 'symbol only'}
    assert cause(record, diagnostic) == 'd'
    assert cause(record, diagnostic | {'target_located': False}) == 'a'
    assert cause(record, diagnostic | {'target_legible': False}) == 'b'
    assert cause(record, diagnostic | {'explicit_numeric_measure': True}) == 'c'
    assert cause(record, diagnostic | {'confidence': .7}) == 'c'
    assert cause(record | {'read_value': {'unreadable': True}}, None) == 'b'
    assert cause({}, None) == 'a'
    assert cause(record | {'before': {'unit': 'mm', 'value': 750}, 'read_value': {'unit': '', 'printed': '750'}}, None) == 'b'
    assert cause(record | {'before': {'unit': 'mm', 'value': 750}, 'read_value': {'unit': '', 'printed': '999'}}, None) == 'c'


def test_standard_cost_and_observed_cache_separate():
    entries = [{'usage': {'prompt_tokens': 100, 'completion_tokens': 20,
                         'prompt_tokens_details': {'cached_tokens': 10}}}]
    c = cost(entries, 'gpt-6.1-sol')
    assert c['usd_standard_uncached'] == pytest.approx(.0004)
    assert c['usd_with_observed_cache'] == pytest.approx(.000381)
    assert c['responses'] == 1
    assert RATES['gpt-6-luna'][:2] == (.1, .5)
