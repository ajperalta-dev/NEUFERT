"""Second-pass dimension verification with a conservative page-context unit step.

Dry-run is local only. The approved run writes to a versioned ledger and never
rewrites source dimensions, OCR text, or the historical first pilot.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import sys
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageDraw
from pydantic import BaseModel, Field

from .config import PRIVATE
from .db import connect
from .unit_context import canonical_unit, declarations, infer

MODEL = "gpt-6-luna"
RUN_ID = "luna-unit-context-v2-full"
PILOT_RUN_ID = "luna-unit-context-v2-pilot"
PILOT_USAGE = PRIVATE / "pass2-runs/sol61-pilot-39-48/luna-frozen/vision-usage-pass2.jsonl"
PILOT_DB = PRIVATE / "neufert.sqlite3"
BASE_DB = PRIVATE / "before-pass2.sqlite3"
BASE_PACKAGE = PRIVATE / "base-package"
PAGE_PRICE = {"input": 0.10, "output": 0.50}  # USD per 1M tokens, Luna standard rate.
MAX_WORKERS = 4
_DB_WRITE_LOCK = threading.Lock()
_TILE_LOCKS: dict[int, threading.Lock] = {}
_TILE_LOCKS_GUARD = threading.Lock()


def _tile_lock(pdf_page: int) -> threading.Lock:
    with _TILE_LOCKS_GUARD:
        return _TILE_LOCKS.setdefault(pdf_page, threading.Lock())


class Reading(BaseModel):
    printed: str
    unit: str = ""
    unreadable: bool = False
    reason: str


class Location(BaseModel):
    tile: int = Field(ge=0, le=8)
    bbox: list[float] = Field(min_length=4, max_length=4)
    found: bool


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() in {
            "OPENAI_API_KEY", "NEUFERT_VERIFY_MODEL", "NEUFERT_VISION_MODEL",
            "NEUFERT_VISION_PROVIDER", "NEUFERT_VISION_URL",
        }:
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def enforce_luna() -> None:
    """Fail closed if either configured model would select anything but Luna."""
    for key in ("NEUFERT_VERIFY_MODEL", "NEUFERT_VISION_MODEL"):
        configured = os.getenv(key)
        if configured and configured != MODEL:
            raise RuntimeError(f"{key}={configured!r}; only {MODEL!r} is allowed. No model call made.")
    if os.getenv("NEUFERT_VISION_PROVIDER", "openai") != "openai":
        raise RuntimeError("This run is locked to the OpenAI provider. No model call made.")
    endpoint = os.getenv("NEUFERT_VISION_URL")
    if endpoint and urlparse(endpoint).hostname != "api.openai.com":
        raise RuntimeError("A non-OpenAI-compatible endpoint is configured; no model call made.")
    os.environ["NEUFERT_VERIFY_MODEL"] = MODEL
    os.environ["NEUFERT_VISION_MODEL"] = MODEL


def _numbers(value: str) -> list[float]:
    normalized = str(value or "").replace("−", "-").replace("–", "-").replace("—", "-")
    return [float(x.replace(",", ".")) for x in re.findall(r"(?<![\w.])\d+(?:[.,]\d+)?", normalized)]


def number_matches(reading: Reading | dict, dimension: dict) -> bool:
    printed = reading.printed if isinstance(reading, Reading) else reading.get("printed", "")
    actual = _numbers(printed)
    expected = [float(dimension["value"])]
    if dimension.get("value_max") is not None:
        expected.append(float(dimension["value_max"]))
    return len(actual) == len(expected) and all(
        math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-8) for a, b in zip(actual, expected)
    )


def _unit_equivalent(read_unit: str, dim_unit: str, reading: Reading | dict, dimension: dict) -> bool:
    ru, du = canonical_unit(read_unit), canonical_unit(dim_unit)
    if not ru or not du:
        return False
    scale = {"m": 1.0, "cm": .01, "mm": .001}
    actual = _numbers(reading.printed if isinstance(reading, Reading) else reading.get("printed", ""))
    expected = [float(dimension["value"])]
    if dimension.get("value_max") is not None:
        expected.append(float(dimension["value_max"]))
    return len(actual) == len(expected) and all(
        math.isclose(a * scale[ru], b * scale[du], rel_tol=1e-6, abs_tol=1e-8)
        for a, b in zip(actual, expected)
    )


@lru_cache(maxsize=64)
def _page_ocr(pdf_page: int) -> tuple[str, list]:
    text_path = BASE_PACKAGE / "text" / f"p{pdf_page:03}.txt"
    words_path = BASE_PACKAGE / "words" / f"p{pdf_page:03}.json"
    text = text_path.read_text(encoding="utf-8", errors="replace") if text_path.exists() else ""
    words = json.loads(words_path.read_text(encoding="utf-8"))["words"] if words_path.exists() else []
    return text, words


def _ocr_context(pdf_page: int) -> tuple[str, list]:
    return _page_ocr(pdf_page)


@lru_cache(maxsize=64)
def _section_declarations(section: str, chapter: str) -> tuple[dict, ...]:
    index_path = BASE_PACKAGE / "pages_index.json"
    if not section or not index_path.exists():
        return ()
    pages = json.loads(index_path.read_text(encoding="utf-8"))
    found = []
    for page in pages:
        if page.get("section") != section or page.get("chapter") != chapter:
            continue
        page_number = int(page["pdf_page"])
        text, words = _page_ocr(page_number)
        found.extend(declarations(text, words, page_number))
    return tuple(found)


def decide(dimension: dict, reading: Reading | dict, pdf_page: int, bbox=None,
           section: str = "", chapter: str = "") -> dict:
    read = reading.model_dump() if isinstance(reading, Reading) else dict(reading)
    before = dimension["status"]
    base = {"status_before": before, "status_after": before, "unit_after": dimension.get("unit", ""),
            "unit_source": None, "unit_citation": None, "unit_bbox": None,
            "unit_page_pdf": None, "unit_inference_outcome": None, "unit_inference_reason": None,
            "unit_inference_candidates": [],
            "verification_level": None, "reason": read.get("reason", ""), "read_value": read}
    if read.get("unreadable"):
        base["reason"] = read.get("reason") or "The dimension is unreadable in the crop."
        return base
    if read.get("unit", "").strip():
        read_unit = canonical_unit(read["unit"])
        stored_unit = canonical_unit(dimension.get("unit", ""))
        explicit_match = (_unit_equivalent(read["unit"], dimension.get("unit", ""), read, dimension)
                          if stored_unit else bool(read_unit) and number_matches(read, dimension))
        if explicit_match:
            base.update(status_after="verified", unit_after=stored_unit or read_unit, verification_level="two_pass",
                        reason="The printed number and explicit crop unit confirm the dimension.")
        else:
            base["reason"] = "Number matches, but the crop unit does not confirm the stored unit."
        return base
    if not number_matches(read, dimension):
        base["reason"] = read.get("reason") or "The printed number does not match the stored number."
        return base

    base.update(status_after="number_confirmed_unit_pending",
                unit_inference_outcome="not_attempted", unit_after="",
                reason="The printed number matches, but no unit is visible in the crop.")
    text, words = _ocr_context(pdf_page)
    page_declarations = declarations(text, words, pdf_page)
    candidates = page_declarations or _section_declarations(section, chapter)
    inferred = infer(dimension, words, text, bbox, candidates=candidates, dimension_page=pdf_page)
    base["unit_inference_outcome"] = inferred["status"]
    base["unit_inference_reason"] = inferred.get("reason")
    base["unit_inference_candidates"] = inferred.get("candidates", [])
    if inferred["status"] == "inferred":
        base.update(status_after="verified_unit_inferred", unit_after=inferred["unit"],
                    unit_source="page_context", unit_citation=inferred["unit_citation"],
                    unit_bbox=inferred["unit_bbox"], unit_page_pdf=inferred.get("unit_page_pdf"),
                    reason="Number matches; unit is explicitly declared in the page context.")
    elif inferred["status"] == "rejected":
        base["unit_inference_outcome"] = "plausibility_rejected"
        base["unit_citation"], base["unit_bbox"] = inferred.get("citation"), inferred.get("bbox")
        base["unit_page_pdf"] = inferred.get("page_pdf")
        base["reason"] = "Number matches, but the context unit failed the plausibility check."
    elif "multiple" in inferred.get("reason", "").casefold():
        base["unit_inference_outcome"] = "ambiguous"
    return base


def _baseline_records() -> list[dict]:
    if not BASE_DB.exists():
        raise RuntimeError(f"Missing pre-pilot baseline {BASE_DB}; refusing to recreate or alter history.")
    conn = sqlite3.connect(BASE_DB)
    conn.row_factory = sqlite3.Row
    records = []
    for row in conn.execute("SELECT id,payload FROM fichas ORDER BY id"):
        ficha = json.loads(row["payload"])
        for index, dimension in enumerate(ficha.get("dimensions", [])):
            if dimension.get("status") not in ("uncertain", "corrected"):
                continue
            records.append({"id": f"{ficha['id']}:{index}", "ficha_id": ficha["id"], "index": index,
                            "pdf_page": int(ficha["pdf_page"]), "book_page": ficha.get("book_page"),
                            "chapter": ficha.get("chapter") or "Unclassified", "section": ficha.get("section") or "",
                            "dimension": dimension})
    conn.close()
    return records


def _pilot_records() -> dict[str, dict]:
    if not PILOT_DB.exists():
        raise RuntimeError(f"Missing historic pilot database {PILOT_DB}.")
    with sqlite3.connect(PILOT_DB) as conn:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='verification_pass2'").fetchone()
        if not exists:
            raise RuntimeError("The historic Luna pilot table is missing.")
        rows = conn.execute("SELECT id,payload FROM verification_pass2 ORDER BY id").fetchall()
    result = {}
    for key, raw in rows:
        record = json.loads(raw)
        model = record.get("model")
        if model != MODEL:
            raise RuntimeError(f"Historic pilot record {key} reports {model!r}; no model call made.")
        result[key] = record
    return result


def _pilot_usage() -> list[dict]:
    if not PILOT_USAGE.exists():
        raise RuntimeError(f"Missing isolated Luna usage log {PILOT_USAGE}.")
    calls = [json.loads(line) for line in PILOT_USAGE.read_text(encoding="utf-8").splitlines() if line.strip()]
    mismatches = [call.get("model") for call in calls if call.get("model") != MODEL]
    if mismatches:
        raise RuntimeError(f"Historic pilot usage log contains a non-Luna model {mismatches[0]!r}; stopped.")
    return calls


def _cost(calls: list[dict]) -> dict:
    input_tokens = sum(c.get("usage", {}).get("prompt_tokens", 0) for c in calls)
    output_tokens = sum(c.get("usage", {}).get("completion_tokens", 0) for c in calls)
    total = input_tokens * PAGE_PRICE["input"] / 1_000_000 + output_tokens * PAGE_PRICE["output"] / 1_000_000
    return {"calls": len(calls), "input_tokens": input_tokens, "output_tokens": output_tokens,
            "estimated_cost_usd": round(total, 6)}


def dry_run() -> dict:
    baseline = _baseline_records()
    pilot = _pilot_records()
    calls = _pilot_usage()
    by_id = {r["id"]: r for r in baseline}
    pilot_results = []
    for key, old in pilot.items():
        source = by_id.get(key)
        if source is None or not 39 <= source["pdf_page"] <= 48:
            continue
        reading = old.get("read_value") or {}
        decision = decide(source["dimension"], reading, source["pdf_page"], old.get("bbox"),
                          source.get("section", ""), source["chapter"])
        pilot_results.append({"id": key, "pdf_page": source["pdf_page"], "chapter": source["chapter"],
                              "model": old["model"], "status_before": source["dimension"]["status"],
                              **decision})

    pilot_before = Counter(r["status_before"] for r in pilot_results)
    pilot_after = Counter(r["status_after"] for r in pilot_results)
    pilot_by_chapter = defaultdict(lambda: {"before": Counter(), "after": Counter()})
    for row in pilot_results:
        pilot_by_chapter[row["chapter"]]["before"][row["status_before"]] += 1
        pilot_by_chapter[row["chapter"]]["after"][row["status_after"]] += 1
    context_counts = Counter(r["unit_inference_outcome"] for r in pilot_results if r["status_before"] in ("uncertain", "corrected") and r["unit_inference_outcome"])
    numeric_unit_pending = sum(r["status_after"] == "number_confirmed_unit_pending" for r in pilot_results)
    ambiguous = [{"id": r["id"], "pdf_page": r["pdf_page"], "chapter": r["chapter"],
                  "reason": r.get("unit_inference_reason"), "candidates": r.get("unit_inference_candidates", [])}
                 for r in pilot_results if r.get("unit_inference_outcome") == "ambiguous"]

    source_uncertain = sum(r["dimension"]["status"] == "uncertain" for r in baseline)
    source_corrected = sum(r["dimension"]["status"] == "corrected" for r in baseline)
    reported_pending = 35  # prior Luna pilot summary supplied for this task
    projected_pending_reported = round(source_uncertain * reported_pending / max(1, pilot_before["uncertain"]))
    projected_pending_recomputed = round(source_uncertain * numeric_unit_pending / max(1, pilot_before["uncertain"]))
    call_cost = _cost(calls)
    scale = len(baseline) / max(1, len(pilot_results))
    full_cost = round(call_cost["estimated_cost_usd"] * scale, 4)
    pilot_cost = call_cost["estimated_cost_usd"]
    remaining_scale = max(0, len(baseline) - len(pilot_results)) / max(1, len(pilot_results))
    estimated = {"dimensions": len(baseline), "pilot_dimensions_to_reprocess": len(pilot_results),
                 "expected_full_run_calls": round(call_cost["calls"] * scale),
                 "expected_new_full_run_cost_usd": full_cost,
                 "historical_pilot_cost_already_spent_usd": pilot_cost,
                 "estimated_lifetime_cost_usd_including_old_pilot": round(full_cost + pilot_cost, 4),
                 "counterfactual_if_old_pilot_were_reused": {
                     "dimensions_needing_calls": max(0, len(baseline) - len(pilot_results)),
                     "expected_calls": round(call_cost["calls"] * remaining_scale),
                     "expected_incremental_cost_usd": round(call_cost["estimated_cost_usd"] * remaining_scale, 4)},
                 "projection_new_states_from_prior_report_35_of_61": {
                     "number_confirmed_unit_pending": projected_pending_reported,
                     "verified_unit_inferred": round(source_uncertain * 0 / max(1, pilot_before["uncertain"]))},
                 "projection_new_states_from_raw_luna_recomputation_40_of_61": {
                     "number_confirmed_unit_pending": projected_pending_recomputed,
                     "verified_unit_inferred": round(source_uncertain * pilot_after["verified_unit_inferred"] / max(1, pilot_before["uncertain"]))}}

    report = {
        "run_id": PILOT_RUN_ID,
        "mode": "dry_run_no_api_calls",
        "model_lock": {"NEUFERT_VERIFY_MODEL": MODEL, "NEUFERT_VISION_MODEL": MODEL},
        "dry_run_api_calls": 0,
        "not_a_dimension_applied": 0,
        "source_population": {"dimensions": len(baseline), "uncertain": source_uncertain, "corrected": source_corrected},
        "pilot": {"dimensions": len(pilot_results), "before": dict(pilot_before), "after": dict(pilot_after),
                  "by_chapter": {chapter: {name: dict(counts) for name, counts in states.items()} for chapter, states in pilot_by_chapter.items()},
                  "new_state_counts": {"number_confirmed_unit_pending": numeric_unit_pending,
                                       "verified_unit_inferred": pilot_after["verified_unit_inferred"]},
                  "unit_context_outcomes": dict(context_counts), "ambiguous_rejections": ambiguous,
                  "stored_model_counts": dict(Counter(r["model"] for r in pilot_results)),
                  "every_historic_api_call": calls},
        "projection": estimated,
        "observed_pilot_usage_cost": call_cost,
        "cost_note": "Projection scales the isolated Luna pilot's logged token use at $0.10/M input and $0.50/M output; excludes retries not represented in successful usage logs and other surcharges.",
        "discrepancy": {"user_reported_number_match_no_unit": 35,
                        "recomputed_from_historic_luna_records": numeric_unit_pending,
                        "explanation": "The raw Luna payload does not preserve a per-item positive locator-confidence flag, so exact numeric matches cannot safely resolve the historical 35-versus-40 difference. The approved run reprocesses all 62 pilot dimensions with Luna and the new locator/read flow; it does not reuse these ambiguous historical decisions."},
        "pilot_rows": pilot_results,
    }
    return report


def _schema() -> None:
    with connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS verification_pass2_units_v2(
          run_id TEXT NOT NULL, id TEXT NOT NULL, ficha_id TEXT NOT NULL,
          dimension_index INTEGER NOT NULL, chapter TEXT, pdf_page INTEGER,
          status_before TEXT NOT NULL, status_after TEXT NOT NULL,
          payload TEXT NOT NULL, updated_at TEXT NOT NULL,
          PRIMARY KEY(run_id,id))""")


def _write_result(run_id: str, source: dict, decision: dict, model: str) -> None:
    if model != MODEL:
        raise RuntimeError(f"Refusing to persist result from {model!r}; expected {MODEL!r}.")
    payload = dict(decision, id=source["id"], chapter=source["chapter"], pdf_page=source["pdf_page"], model=model, run_id=run_id)
    with _DB_WRITE_LOCK:
        with connect() as conn:
            conn.execute("""INSERT OR REPLACE INTO verification_pass2_units_v2
              (run_id,id,ficha_id,dimension_index,chapter,pdf_page,status_before,status_after,payload,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?)""",
              (run_id, source["id"], source["ficha_id"], source["index"], source["chapter"], source["pdf_page"],
               decision["status_before"], decision["status_after"], json.dumps(payload, ensure_ascii=False),
               datetime.now(timezone.utc).isoformat()))


def _word_bbox(words: list, dimension: dict) -> list[float] | None:
    from .verify_pass2 import locate
    _, bbox = locate(words, dimension)
    return bbox


def _page_crop(pdf_page: int, bbox: list[float], path: Path) -> None:
    image_path = BASE_PACKAGE / "pages" / f"p{pdf_page:03}.webp"
    with Image.open(image_path) as source:
        image = source.convert("L")
        w, h = image.size
        x0, y0, x1, y1 = [max(0., min(1., float(v))) for v in bbox]
        if x1 <= x0 or y1 <= y0:
            raise ValueError("Invalid normalized bbox; refusing to create an empty crop.")
        margin = max(32, int(.15 * max((x1-x0)*w, (y1-y0)*h)))
        rect = (max(0, int(x0*w)-margin), max(0, int(y0*h)-margin),
                min(w, int(x1*w)+margin), min(h, int(y1*h)+margin))
        image.crop(rect).save(path, format="PNG")


def _valid_bbox(bbox) -> bool:
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return False
    try:
        x0, y0, x1, y1 = [float(v) for v in bbox]
    except (TypeError, ValueError):
        return False
    return (all(math.isfinite(v) and 0 <= v <= 1 for v in (x0, y0, x1, y1))
            and x1 > x0 and y1 > y0)


def _tiles_unlocked(pdf_page: int, out_dir: Path) -> tuple[Path, list[list[float]]]:
    image_path = BASE_PACKAGE / "pages" / f"p{pdf_page:03}.webp"
    with Image.open(image_path) as source:
        image = source.convert("L")
    w, h = image.size
    tile_paths, boxes = [], []
    for n in range(9):
        x, y = n % 3, n // 3
        box = [max(0, x/3-.025), max(0, y/3-.025), min(1, (x+1)/3+.025), min(1, (y+1)/3+.025)]
        tile_path = out_dir / f"p{pdf_page:03}_tile{n}.png"
        image.crop((int(box[0]*w), int(box[1]*h), int(box[2]*w), int(box[3]*h))).save(tile_path)
        tile_paths.append(tile_path)
        boxes.append(box)
    sheet = Image.new("RGB", (1800, 2475), "white")
    draw = ImageDraw.Draw(sheet)
    for n, tile_path in enumerate(tile_paths):
        with Image.open(tile_path) as tile:
            tile = tile.convert("RGB")
            tile.thumbnail((590, 790))
            x, y = n % 3 * 600, n // 3 * 825
            sheet.paste(tile, (x, y+28))
            draw.text((x+5, y+4), str(n), fill="black")
    contact = out_dir / f"p{pdf_page:03}_tiles.png"
    sheet.save(contact)
    return contact, boxes


def _tiles(pdf_page: int, out_dir: Path) -> tuple[Path, list[list[float]]]:
    with _tile_lock(pdf_page):
        return _tiles_unlocked(pdf_page, out_dir)


def _vision_provider():
    # Import only after the model lock is checked; no provider fallback is allowed.
    from .vision_fichas import VisionProvider
    os.environ["NEUFERT_VISION_USAGE_FILE"] = "vision-usage-unit-context-v2-full.jsonl"
    provider = VisionProvider()
    if provider.model != MODEL:
        raise RuntimeError(f"Provider selected {provider.model!r}; stopped before API request.")
    return provider


def _call(provider, image: bytes, prompt: str, schema, stage: str):
    if provider.model != MODEL or os.getenv("NEUFERT_VISION_MODEL") != MODEL:
        raise RuntimeError("Model changed during run; stopped before API request.")
    from .vision_fichas import validated
    result, usage = validated(provider, image, prompt, schema, stage=stage)
    if provider.model != MODEL:
        raise RuntimeError("Provider model changed during call; stopped.")
    return result, usage


def _read_new(provider, source: dict, crop_dir: Path) -> dict:
    page = source["pdf_page"]
    words_path = BASE_PACKAGE / "words" / f"p{page:03}.json"
    words = json.loads(words_path.read_text(encoding="utf-8"))["words"] if words_path.exists() else []
    dimension = source["dimension"]
    method, bbox = "word_coordinates", _word_bbox(words, dimension)
    if bbox is None:
        contact, tile_boxes = _tiles(page, crop_dir)
        label = re.sub(r"\d+(?:[.,]\d+)?", "[redacted]", dimension.get("label", ""))
        context = re.sub(r"\d+(?:[.,]\d+)?", "[redacted]", dimension.get("context", ""))
        location, _ = _call(provider, contact.read_bytes(),
            "Locate the labelled dimension only; do not infer its value. Return a normalized bbox within tile "
            "0-8. If not found set found=false. Label: " + label + "; context: " + context +
            ". Schema: " + json.dumps(Location.model_json_schema()), Location, "locate_dimension")
        if not location.found:
            read = Reading(printed="", unit="", unreadable=True, reason="Dimension could not be located in the page image.")
            return {"reading": read, "bbox": None, "locator": "not_found"}
        tile = tile_boxes[location.tile]
        local = location.bbox
        bbox = [tile[0]+local[0]*(tile[2]-tile[0]), tile[1]+local[1]*(tile[3]-tile[1]),
                tile[0]+local[2]*(tile[2]-tile[0]), tile[1]+local[3]*(tile[3]-tile[1])]
        method = "luna_tiles"
    if not _valid_bbox(bbox):
        read = Reading(printed="", unit="", unreadable=True, reason="The locator returned an invalid page bbox.")
        return {"reading": read, "bbox": None, "locator": "invalid_bbox"}
    crop_path = crop_dir / f"p{page:03}_{source['ficha_id']}_{source['index']}.png"
    _page_crop(page, bbox, crop_path)
    label = re.sub(r"\d+(?:[.,]\d+)?", "[redacted]", dimension.get("label", ""))
    context = re.sub(r"\d+(?:[.,]\d+)?", "[redacted]", dimension.get("context", ""))
    read, _ = _call(provider, crop_path.read_bytes(),
        "Read only the explicitly printed number or range and explicit unit corresponding to the label. "
        "Do not infer a unit from conventions or surrounding knowledge. If unreadable or ambiguous, mark it "
        "unreadable. Label: " + label + "; context: " + context + ". Schema: " +
        json.dumps(Reading.model_json_schema()), Reading, "read_dimension")
    return {"reading": read, "bbox": bbox, "locator": method}


def approved_full_run() -> dict:
    baseline = _baseline_records()
    # Validate the historic run's provenance, but do not reuse its ambiguous reads.
    _pilot_records()
    _schema()
    crop_dir = PRIVATE / "pass2-runs" / RUN_ID / "crops"
    crop_dir.mkdir(parents=True, exist_ok=True)
    provider = _vision_provider()
    with connect() as conn:
        done = {r[0] for r in conn.execute("SELECT id FROM verification_pass2_units_v2 WHERE run_id=?", (RUN_ID,))}
    todo = [source for source in baseline if source["id"] not in done]

    def process(source: dict) -> None:
        result = _read_new(provider, source, crop_dir)
        reading, bbox, locator, model = result["reading"], result["bbox"], result["locator"], provider.model
        reading = reading.model_dump() if isinstance(reading, Reading) else reading
        decision = decide(source["dimension"], reading, source["pdf_page"], bbox,
                          source.get("section", ""), source["chapter"])
        decision.update(locator=locator, bbox=bbox, timestamp=datetime.now(timezone.utc).isoformat())
        _write_result(RUN_ID, source, decision, model)
        print(source["id"], decision["status_after"], flush=True)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="luna-verify") as pool:
        for processed, _ in enumerate(pool.map(process, todo), start=1):
            if processed % 25 == 0:
                print(f"progress {len(done)+processed}/{len(baseline)}", flush=True)
    return final_report()


def final_report() -> dict:
    with connect() as conn:
        rows = conn.execute("SELECT id,chapter,status_before,status_after,payload FROM verification_pass2_units_v2 WHERE run_id=?", (RUN_ID,)).fetchall()
    before, after = Counter(), Counter()
    chapters = defaultdict(lambda: {"before": Counter(), "after": Counter()})
    payloads = []
    for row_id, chapter, status_before, status_after, raw in rows:
        before[status_before] += 1
        after[status_after] += 1
        chapters[chapter]["before"][status_before] += 1
        chapters[chapter]["after"][status_after] += 1
        payloads.append(json.loads(raw))
    usage_path = PRIVATE / "vision-usage-unit-context-v2-full.jsonl"
    calls = [json.loads(line) for line in usage_path.read_text(encoding="utf-8").splitlines() if line.strip()] if usage_path.exists() else []
    if any(c.get("model") != MODEL for c in calls):
        raise RuntimeError("Non-Luna model found in full-run usage log; report stopped.")
    pilot_calls = _pilot_usage()
    audited_calls = ([dict(call, run_source=PILOT_RUN_ID) for call in pilot_calls]
                     + [dict(call, run_source=RUN_ID) for call in calls])
    result = {"run_id": RUN_ID, "model": MODEL, "processed_dimensions": len(rows),
              "not_a_dimension_applied": 0,
              "before": dict(before), "after": dict(after),
              "by_chapter": {chapter: {name: dict(counts) for name, counts in states.items()} for chapter, states in chapters.items()},
              "inferred_by_context": sum(p.get("status_after") == "verified_unit_inferred" for p in payloads),
              "ambiguous_rejections": [{"id": p.get("id"), "pdf_page": p.get("pdf_page"),
                                        "chapter": p.get("chapter"), "reason": p.get("unit_inference_reason"),
                                        "candidates": p.get("unit_inference_candidates", [])}
                                       for p in payloads if p.get("unit_inference_outcome") == "ambiguous"],
              "plausibility_rejections": [{"id": p.get("id"), "pdf_page": p.get("pdf_page"),
                                            "chapter": p.get("chapter"), "citation": p.get("unit_citation"),
                                            "bbox": p.get("unit_bbox"), "reason": p.get("unit_inference_reason")}
                                           for p in payloads if p.get("unit_inference_outcome") == "plausibility_rejected"],
              "models_by_call": audited_calls,
              "usage_cost": {"historical_pilot": _cost(pilot_calls), "new_full_run": _cost(calls),
                             "total_including_pilot": _cost(audited_calls)}}
    out = PRIVATE / "reports"
    out.mkdir(exist_ok=True)
    (out / "segunda_pasada_unidad_contexto_v2.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Estimate the full run without API calls.")
    mode.add_argument("--approved-full-run", action="store_true", help="Execute the full second pass using Luna only.")
    parser.add_argument("--env-file", type=Path, default=Path(__file__).resolve().parents[1] / ".env")
    args = parser.parse_args()
    _load_env(args.env_file)
    enforce_luna()
    if args.dry_run:
        result = dry_run()
        output = PRIVATE / "reports" / "segunda_pasada_unidad_contexto_v2_dry_run.json"
        output.parent.mkdir(exist_ok=True)
        # Keep the long per-call audit local and separate from historic reports.
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        concise = dict(result)
        concise["pilot"] = {k: v for k, v in result["pilot"].items() if k != "every_historic_api_call"}
        concise["historic_pilot_api_call_count"] = len(result["pilot"]["every_historic_api_call"])
        concise.pop("pilot_rows", None)
        print(json.dumps(concise, ensure_ascii=False, indent=2))
        print(f"Informe: {output}")
        return
    if os.getenv("OPENAI_API_KEY", "") == "":
        raise RuntimeError("OPENAI_API_KEY missing; no API calls made.")
    result = approved_full_run()
    print(json.dumps({k: v for k, v in result.items() if k != "models_by_call"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
