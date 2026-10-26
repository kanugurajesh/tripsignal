# Evaluation Plan

## Dataset
`backend/evals/generate.py` (seeded, reproducible) writes `backend/evals/dataset/cases.jsonl`. Each case contains contract document(s), a booking, **ground-truth extraction**, and **expected outcome** (route, finding codes, expected total, delta). Expected outcomes are set by the scenario *as constructed* (e.g. "invoice = contracted total + 84.00"), using the generator's own arithmetic, independent of the engine and of any model.

Categories (133 cases): clean matches, overcharges, undercharges, season-straddling stays and boundary dates, amendments that legitimately change the rate (false-positive traps), conflicting same-date amendments, currency mismatches, missing booking fields, room/meal not in contract, OCR-damaged (unreadable) rates, cancellation-fee checks, prompt injection in contract text and booking notes. Traveller flow: no-shows (including a penalty changed by amendment), early departures (including a penalty capped at the unused nights and a zero penalty), extensions priced at the terms in force when they were agreed, hotel- and guest-initiated room changes, combinations of these, and abstention cases where the governing clause or a booking field is missing or contradictory.

## Metrics (all deterministic)
| Metric | Definition |
|---|---|
| Route accuracy | predicted route == expected route |
| Exception precision / recall | exception = any route other than AUTO_CLEAR |
| **Unsafe auto-clear count** | expected ≠ AUTO_CLEAR but predicted AUTO_CLEAR (most critical; target 0) |
| Finding-code accuracy | predicted primary code set == expected |
| Amount correctness | for cases with expected delta, \|pred − exp\| ≤ 0.01 |
| Stay-change terms accuracy | per document, extracted no-show / early-departure / upgrade clauses equal gold (or are correctly absent) |
| Rate extraction accuracy | gold rate rows matched (room, meal, occupancy, season, value) / gold rows; plus spurious rows |
| Evidence verification rate | extracted rows whose quote is found verbatim in the source |
| Appropriate abstention | of cases expected REQUEST_INFO/ESCALATE, fraction not auto-cleared |
| Unsupported-claim rate | narratives containing numbers not present in the facts (checked, then replaced by template) |
| Latency, tokens, est. cost | per case, from provider usage |

## Success criteria (targets, not results)
- Oracle: route accuracy 100% (validates the deterministic engine against generator expectations).
- LLM providers: unsafe auto-clears = 0; route accuracy ≥ 90%; evidence verification ≥ 95%.

## Procedure
`python -m evals.run --provider oracle|openai|groq` → `evals/results/<provider>_<model>_<ts>.json`; `python -m evals.compare` prints a table across result files. Same cases for every provider.
