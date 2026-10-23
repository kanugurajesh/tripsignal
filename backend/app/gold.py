"""Loaders for the synthetic dataset (documents, ground-truth extraction, cases)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.domain import ContractDocument

DATASET = Path(__file__).resolve().parent.parent / "evals" / "dataset"


def _rows(name: str) -> list[dict[str, Any]]:
    with open(DATASET / name, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_gold() -> dict[str, dict[str, Any]]:
    return {r["document_id"]: r["gold"] for r in _rows("documents.jsonl")}


def load_documents() -> dict[str, ContractDocument]:
    return {r["document_id"]: ContractDocument.model_validate(r) for r in _rows("documents.jsonl")}


def load_cases() -> list[dict[str, Any]]:
    return _rows("cases.jsonl")
