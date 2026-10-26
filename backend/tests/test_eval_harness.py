"""Regression: the deterministic engine must agree with every expected outcome
in the dataset when extraction is perfect (oracle)."""

from app.config import Settings
from app.gold import load_cases
from evals import run as runner


def test_dataset_has_expected_coverage():
    cases = load_cases()
    cats = {c["category"] for c in cases}
    assert len(cases) >= 100
    assert {"injection", "version_conflict", "unreadable", "currency", "missing_field", "cancellation",
            "amendment", "season_boundary", "rounding_trap", "no_show", "early_departure", "extension",
            "room_change", "combined"} <= cats
    assert len({c["case_id"] for c in cases}) == len(cases)


def test_oracle_eval_is_perfect(monkeypatch):
    monkeypatch.setattr(runner, "get_settings", lambda: Settings(_env_file=None))  # type: ignore[call-arg]
    res = runner.evaluate("oracle", limit=None, narratives=False, workers=2)
    s = res["summary"]
    assert s["route_accuracy"] == 1.0 and s["code_set_accuracy"] == 1.0 and s["amount_accuracy"] == 1.0
    assert s["unsafe_auto_clears"] == 0 and s["rate_row_recall"] == 1.0 and s["stay_policy_accuracy"] == 1.0
