"""Compare saved evaluation runs side by side.

    python -m evals.compare                # latest run per provider/model
    python -m evals.compare --all
"""

from __future__ import annotations

import argparse
import json

from evals.run import RESULTS

METRICS = [
    "route_accuracy", "code_set_accuracy", "unsafe_auto_clears", "exception_precision", "exception_recall",
    "amount_accuracy", "rate_row_recall", "spurious_rate_rows", "evidence_verified_rate",
    "effective_date_accuracy", "cancellation_terms_accuracy", "narratives_rejected_unsupported_numbers",
    "llm_calls", "input_tokens", "output_tokens", "est_cost_usd", "mean_llm_latency_ms",
]


def load_runs(all_runs: bool = False) -> list[dict]:
    runs = [json.loads(p.read_text(encoding="utf-8")) | {"_file": p.name} for p in sorted(RESULTS.glob("*.json"))]
    if all_runs:
        return runs
    latest: dict[tuple, dict] = {}
    for r in runs:
        latest[(r["meta"]["provider"], r["meta"]["model"], r["meta"]["narratives"])] = r
    return list(latest.values())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    runs = load_runs(ap.parse_args().all)
    if not runs:
        print("no results yet; run `python -m evals.run` first")
        return
    heads = [f"{r['meta']['provider']}:{r['meta']['model']}{' +narr' if r['meta']['narratives'] else ''}" for r in runs]
    w = max(len(h) for h in heads) + 2
    print("metric".ljust(40) + "".join(h.rjust(w) for h in heads))
    for m in METRICS:
        print(m.ljust(40) + "".join(str(r["summary"].get(m)).rjust(w) for r in runs))
    print("cases".ljust(40) + "".join(str(r["meta"]["cases"]).rjust(w) for r in runs))
    print("dataset".ljust(40) + "".join(r["meta"]["dataset_sha256"].rjust(w) for r in runs))


if __name__ == "__main__":
    main()
