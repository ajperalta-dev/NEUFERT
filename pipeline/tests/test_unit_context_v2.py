from pipeline import verify_pass2_units as verify
from pipeline.hybrid_api import label


def dimension(**changes):
    value = {
        "status": "uncertain",
        "label": "Door width",
        "value": 900.0,
        "value_max": None,
        "unit": "mm",
        "context": "Figure 2, door opening width",
    }
    value.update(changes)
    return value


def test_number_match_without_crop_unit_stays_pending_when_context_has_no_declaration(monkeypatch):
    monkeypatch.setattr(verify, "_ocr_context", lambda page: ("Door width", []))
    result = verify.decide(dimension(), {"printed": "900", "unit": "", "unreadable": False, "reason": "900 is visible"}, 20)
    assert result["status_after"] == "number_confirmed_unit_pending"
    assert result["unit_after"] == ""
    assert result["unit_source"] is None


def test_unique_page_declaration_infers_unit_with_literal_and_bbox(monkeypatch):
    words = [["All", .1, .1, .16, .13], ["dimensions", .17, .1, .34, .13],
             ["in", .35, .1, .38, .13], ["mm", .39, .1, .44, .13]]
    monkeypatch.setattr(verify, "_ocr_context", lambda page: ("All dimensions in mm", words))
    result = verify.decide(dimension(), {"printed": "900", "unit": "", "unreadable": False, "reason": "900 is visible"}, 20)
    assert result["status_after"] == "verified_unit_inferred"
    assert result["unit_after"] == "mm"
    assert result["unit_source"] == "page_context"
    assert result["unit_citation"] == "All dimensions in mm"
    assert result["unit_bbox"] == [.1, .1, .44, .13]
    assert result["verification_level"] is None


def test_unique_declaration_in_same_section_can_supply_context_bbox(monkeypatch):
    declaration = ({"unit": "mm", "citation": "All dimensions in mm",
                    "bbox": [.1, .1, .44, .13], "page_pdf": 19},)
    monkeypatch.setattr(verify, "_ocr_context", lambda page: ("Door width", []))
    monkeypatch.setattr(verify, "_section_declarations", lambda section, chapter: declaration)
    result = verify.decide(dimension(), {"printed": "900", "unit": "", "unreadable": False, "reason": "900"},
                           20, section="Residential", chapter="RESIDENTIAL BUILDINGS")
    assert result["status_after"] == "verified_unit_inferred"
    assert result["unit_page_pdf"] == 19
    assert result["unit_bbox"] == [.1, .1, .44, .13]


def test_ambiguous_page_units_remain_pending(monkeypatch):
    words = [["Dimensions", .1, .1, .25, .13], ["in", .26, .1, .29, .13], ["mm", .3, .1, .36, .13],
             ["Units", .1, .8, .16, .83], [":", .17, .8, .18, .83], ["cm", .19, .8, .25, .83]]
    monkeypatch.setattr(verify, "_ocr_context", lambda page: ("Dimensions in mm\nUnits: cm", words))
    result = verify.decide(dimension(), {"printed": "900", "unit": "", "unreadable": False, "reason": "number"}, 20)
    assert result["status_after"] == "number_confirmed_unit_pending"
    assert result["unit_inference_outcome"] == "ambiguous"


def test_implausible_context_unit_is_not_applied(monkeypatch):
    words = [["All", .1, .1, .16, .13], ["dimensions", .17, .1, .34, .13],
             ["in", .35, .1, .38, .13], ["mm", .39, .1, .44, .13]]
    monkeypatch.setattr(verify, "_ocr_context", lambda page: ("All dimensions in mm", words))
    d = dimension(value=500000, context="Human standing height")
    result = verify.decide(d, {"printed": "500000", "unit": "", "unreadable": False, "reason": "number"}, 20)
    assert result["status_after"] == "number_confirmed_unit_pending"
    assert result["unit_after"] == ""
    assert result["unit_inference_outcome"] == "plausibility_rejected"


def test_explicit_crop_unit_verifies_without_inference(monkeypatch):
    monkeypatch.setattr(verify, "_ocr_context", lambda page: (_ for _ in ()).throw(AssertionError("context must not be read")))
    result = verify.decide(dimension(), {"printed": "900", "unit": "mm", "unreadable": False, "reason": "900 mm"}, 20)
    assert result["status_after"] == "verified"
    assert result["verification_level"] == "two_pass"
    assert result["unit_source"] is None


def test_explicit_crop_unit_can_fill_an_empty_stored_unit():
    result = verify.decide(dimension(unit=""),
                           {"printed": "900", "unit": "mm", "unreadable": False, "reason": "900 mm"}, 20)
    assert result["status_after"] == "verified"
    assert result["unit_after"] == "mm"


def test_explicit_crop_unit_allows_equivalent_metric_representation():
    result = verify.decide(dimension(value=1200, unit="mm"),
                           {"printed": "1.2", "unit": "m", "unreadable": False, "reason": "1.2 m"}, 20)
    assert result["status_after"] == "verified"
    assert result["unit_after"] == "mm"


def test_different_number_preserves_prior_status_and_value():
    d = dimension(status="corrected", value=900)
    result = verify.decide(d, {"printed": "850", "unit": "mm", "unreadable": False, "reason": "850 mm"}, 20)
    assert result["status_after"] == "corrected"
    assert result["status_before"] == "corrected"
    assert d["value"] == 900


def test_new_status_labels_are_exactly_the_requested_spanish_copy():
    assert label({"status": "number_confirmed_unit_pending"}) == "Número confirmado, unidad pendiente"
    assert label({"status": "verified_unit_inferred"}) == "Unidad inferida del contexto de la página"


def test_invalid_locator_bbox_is_rejected_before_crop():
    assert verify._valid_bbox([.1, .1, .9, .9])
    assert not verify._valid_bbox([.8, .1, .2, .9])
    assert not verify._valid_bbox([-.1, .1, .9, .9])
    assert not verify._valid_bbox([.1, .1, float("nan"), .9])
