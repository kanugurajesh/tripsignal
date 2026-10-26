"""Evaluation runner. Same cases for every provider; deterministic scoring.

    python -m evals.run --provider oracle
    python -m evals.run --provider openai --narratives
    python -m evals.run --provider groq --limit 20
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.domain import Booking, ContractTerms
from app.gold import DATASET, load_cases, load_documents, load_gold
from app.pipeline.engine import norm
from app.pipeline.extraction import PROMPT_VERSION
from app.pipeline.run import ExtractionCache, run_audit
from app.providers import build_provider

RESULTS = Path(__file__).parent / "results"


def _key(r: dict[str, Any] | Any) -> tuple:
    g = r if isinstance(r, dict) else r.model_dump(mode="json")
    return (norm(g["room_type"]), g["meal_plan"], g["occupancy"], str(g["season_start"]), str(g["season_end"]))


def score_extraction(doc_id: str, gold: dict[str, Any], terms: ContractTerms | None, error: str | None) -> dict:
    gold_rows = {_key(r): (Decimal(r["nightly_rate"]) if r["nightly_rate"] else None) for r in gold["rates"]}
    if terms is None:
        return {"document_id": doc_id, "ok": False, "error": error, "gold_rows": len(gold_rows), "correct_rows": 0,
                "spurious_rows": 0, "extracted_rows": 0, "verified_rows": 0, "effective_correct": False,
                "cancellation_correct": False, "stay_policies_correct": False}
    got = {}
    for r in terms.rates:
        got[_key(r)] = r
    correct = sum(1 for k, v in gold_rows.items() if k in got and got[k].nightly_rate == v)
    gc = gold["cancellation"]
    canc_ok = (gc is None and terms.cancellation is None) or (
        gc is not None and terms.cancellation is not None
        and (gc["free_cancellation_days"], gc["penalty_nights"])
        == (terms.cancellation.free_cancellation_days, terms.cancellation.penalty_nights))
    policies_ok = all(
        (gold.get(k) is None and getattr(terms, k) is None) or (
            gold.get(k) is not None and getattr(terms, k) is not None
            and {f: v for f, v in gold[k].items() if f != "evidence"}
            == getattr(terms, k).model_dump(exclude={"evidence"}))
        for k in ("no_show", "early_departure", "upgrade"))
    return {
        "document_id": doc_id, "ok": True, "error": None, "gold_rows": len(gold_rows), "correct_rows": correct,
        "extracted_rows": len(terms.rates), "spurious_rows": sum(1 for k in got if k not in gold_rows),
        "verified_rows": sum(1 for r in terms.rates if r.evidence.verified),
        "unverified_examples": [r.evidence.reason for r in terms.rates if not r.evidence.verified][:3],
        "effective_correct": str(terms.effective_from) == gold["effective"]["effective_from"],
        "cancellation_correct": canc_ok, "stay_policies_correct": policies_ok, "schema_errors": terms.schema_errors,
    }


def evaluate(provider_name: str, *, limit: int | None, narratives: bool, workers: int) -> dict[str, Any]:
    settings = get_settings()
    gold, docs, cases = load_gold(), load_documents(), load_cases()[: limit or None]
    provider = build_provider(settings, provider_name, gold=gold)  # type: ignore[arg-type]
    cache = ExtractionCache()
    t0 = time.perf_counter()

    needed = sorted({d for c in cases for d in c["document_ids"]})
    doc_scores, extraction_usage = [], []
    for doc_id in needed:  # extract each document once; cases then hit the cache
        out, _ = cache.get_or_extract(docs[doc_id], provider)
        extraction_usage += out.usage
        doc_scores.append(score_extraction(doc_id, gold[doc_id], out.terms, out.error))

    def one(c: dict[str, Any]) -> dict[str, Any]:
        booking = Booking.model_validate(c["booking"])
        t = time.perf_counter()
        run = run_audit(booking, [docs[d] for d in c["document_ids"]], provider, cache=cache,
                        narrative_provider=provider if narratives else None, with_narrative=narratives)
        r, exp = run.result, c["expected"]
        pred_codes = sorted(x.value for x in r.codes)
        amount_ok = None
        if exp["delta"] is not None:
            amount_ok = r.delta is not None and abs(r.delta - Decimal(exp["delta"])) <= Decimal("0.01") and \
                r.expected_amount is not None and abs(r.expected_amount - Decimal(exp["expected_amount"])) <= Decimal("0.01")
        return {
            "case_id": c["case_id"], "category": c["category"], "description": c["description"],
            "expected_route": exp["route"], "predicted_route": r.route.value,
            "expected_codes": exp["codes"], "predicted_codes": pred_codes,
            "expected_delta": exp["delta"], "predicted_delta": str(r.delta) if r.delta is not None else None,
            "route_ok": r.route.value == exp["route"], "codes_ok": pred_codes == exp["codes"], "amount_ok": amount_ok,
            "narrative_source": run.narrative.source if run.narrative else None,
            "narrative_rejected": run.narrative.rejected_reason if run.narrative else None,
            "latency_ms": round((time.perf_counter() - t) * 1000, 1),
            "usage": run.usage,
        }

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        rows = list(ex.map(one, cases))
    elapsed = time.perf_counter() - t0
    return {
        "meta": {
            "provider": provider.name, "model": provider.model, "prompt_version": PROMPT_VERSION,
            "narratives": narratives, "cases": len(rows), "documents": len(doc_scores),
            "dataset_sha256": hashlib.sha256((DATASET / "cases.jsonl").read_bytes()
                                             + (DATASET / "documents.jsonl").read_bytes()).hexdigest()[:16],
            "run_at": datetime.now(UTC).isoformat(timespec="seconds"), "wall_time_s": round(elapsed, 1),
        },
        "summary": summarize(rows, doc_scores, extraction_usage),
        "by_category": by_category(rows),
        "documents": doc_scores,
        "cases": rows,
    }


def _ratio(a: int, b: int) -> float | None:
    return round(a / b, 4) if b else None


def summarize(rows: list[dict], docs: list[dict], extraction_usage: list[dict]) -> dict[str, Any]:
    exc_exp = [r["expected_route"] != "AUTO_CLEAR" for r in rows]
    exc_pred = [r["predicted_route"] != "AUTO_CLEAR" for r in rows]
    tp = sum(e and p for e, p in zip(exc_exp, exc_pred, strict=True))
    fp = sum((not e) and p for e, p in zip(exc_exp, exc_pred, strict=True))
    fn = sum(e and (not p) for e, p in zip(exc_exp, exc_pred, strict=True))
    should_abstain = [r for r in rows if r["expected_route"] in ("REQUEST_INFO", "ESCALATE")]
    amount_rows = [r for r in rows if r["amount_ok"] is not None]
    narr = [r for r in rows if r["narrative_source"] is not None and r["expected_route"] != "AUTO_CLEAR"]
    usage = extraction_usage + [u for r in rows for u in r["usage"] if u.get("stage") == "narrative"]
    costs = [u["cost_usd"] for u in usage if u.get("cost_usd") is not None]
    gold_rows = sum(d["gold_rows"] for d in docs)
    extracted = sum(d["extracted_rows"] for d in docs)
    return {
        "route_accuracy": _ratio(sum(r["route_ok"] for r in rows), len(rows)),
        "code_set_accuracy": _ratio(sum(r["codes_ok"] for r in rows), len(rows)),
        "exception_precision": _ratio(tp, tp + fp), "exception_recall": _ratio(tp, tp + fn),
        "false_positive_rate": _ratio(fp, sum(not e for e in exc_exp)),
        "false_negative_rate": _ratio(fn, sum(exc_exp)),
        "unsafe_auto_clears": sum(1 for r in rows if r["expected_route"] != "AUTO_CLEAR"
                                  and r["predicted_route"] == "AUTO_CLEAR"),
        "appropriate_abstention_rate": _ratio(sum(r["predicted_route"] != "AUTO_CLEAR" for r in should_abstain),
                                              len(should_abstain)),
        "amount_accuracy": _ratio(sum(r["amount_ok"] for r in amount_rows), len(amount_rows)),
        "extraction_documents_ok": _ratio(sum(d["ok"] for d in docs), len(docs)),
        "rate_row_recall": _ratio(sum(d["correct_rows"] for d in docs), gold_rows),
        "spurious_rate_rows": sum(d["spurious_rows"] for d in docs),
        "evidence_verified_rate": _ratio(sum(d["verified_rows"] for d in docs), extracted),
        "effective_date_accuracy": _ratio(sum(d["effective_correct"] for d in docs), len(docs)),
        "cancellation_terms_accuracy": _ratio(sum(d["cancellation_correct"] for d in docs), len(docs)),
        "stay_policy_accuracy": _ratio(sum(d.get("stay_policies_correct", False) for d in docs), len(docs)),
        "narratives_attempted": len(narr),
        "narratives_from_llm": sum(1 for r in narr if r["narrative_source"] not in ("template", None)),
        "narratives_rejected_unsupported_numbers": sum(1 for r in narr if (r["narrative_rejected"] or "").startswith("unsupported")),
        "llm_calls": len(usage),
        "input_tokens": sum(u.get("input_tokens") or 0 for u in usage),
        "output_tokens": sum(u.get("output_tokens") or 0 for u in usage),
        "est_cost_usd": round(sum(costs), 4) if costs else None,
        "mean_llm_latency_ms": round(sum(u["latency_ms"] for u in usage) / len(usage), 1) if usage else None,
    }


def by_category(rows: list[dict]) -> dict[str, dict[str, Any]]:
    g: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        g[r["category"]].append(r)
    return {k: {"n": len(v), "route_accuracy": _ratio(sum(r["route_ok"] for r in v), len(v)),
                "unsafe_auto_clears": sum(1 for r in v if r["expected_route"] != "AUTO_CLEAR"
                                          and r["predicted_route"] == "AUTO_CLEAR")}
            for k, v in sorted(g.items())}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["oracle", "openai", "groq"], default="oracle")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--narratives", action="store_true", help="also generate + check LLM narratives")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    res = evaluate(args.provider, limit=args.limit, narratives=args.narratives, workers=args.workers)
    RESULTS.mkdir(exist_ok=True)
    m = res["meta"]
    name = f"{m['provider']}_{m['model'].replace('/', '-')}_{m['run_at'].replace(':', '').replace('+0000', 'Z')}.json"
    (RESULTS / name).write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps({"file": str(RESULTS / name), **res["summary"]}, indent=1))
    bad = [c for c in res["cases"] if not c["route_ok"]]
    for c in bad[:15]:
        print(f"  MISS {c['case_id']} [{c['category']}] {c['description']}: expected {c['expected_route']} "
              f"{c['expected_codes']} got {c['predicted_route']} {c['predicted_codes']}")


if __name__ == "__main__":
    main()
