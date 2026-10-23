"""Deterministic scan of untrusted text for instruction-like content.

This is defence in depth: documents are also delimited and labelled as data in
prompts, and the model has no tools. A hit never blocks processing; it forces
the case to human review so no injected text can auto-clear a booking.
"""

import re

_PATTERNS = [
    r"ignore\s+(all\s+|any\s+)?(previous|prior|above|earlier)\s+(instructions|rules|prompts?)",
    r"disregard\s+(all\s+|the\s+)?(previous|prior|above|system|earlier)",
    r"\bsystem\s+prompt\b",
    r"\byou\s+are\s+now\b",
    r"\bnew\s+instructions?\b",
    r"</?\s*(system|assistant|instructions?)\s*>",
    r"^\s*(system|assistant)\s*:",
    r"\b(mark|treat|classify|report)\b[^.\n]{0,60}\b(as\s+)?(matched|match|approved|cleared|compliant|correct)\b",
    r"\bdo\s+not\s+(flag|report|escalate|mention)\b",
    r"\b(auto[- ]?approve|approve\s+automatically)\b",
    r"\breveal\b[^.\n]{0,40}\b(key|secret|prompt|password)\b",
]
_RX = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in _PATTERNS]


def scan(text: str) -> list[str]:
    """Return matched snippets (deduplicated, in order)."""
    hits: list[str] = []
    for rx in _RX:
        for m in rx.finditer(text or ""):
            start = text.rfind("\n", 0, m.start()) + 1  # snap to line start for a readable snippet
            end = text.find("\n", m.end())
            snippet = text[start : end if end != -1 else len(text)].strip()[:240]
            if snippet not in hits:
                hits.append(snippet)
    return hits
