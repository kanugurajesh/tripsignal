# Architecture

```
contract text (untrusted) ──► injection scan (deterministic) ─┐
                         └──► LLM extraction (structured JSON, quotes) ──► schema validation (Pydantic)
                                                                         ──► evidence verification (quote ⊂ source text)
booking + invoice (structured) ───────────────────────────────────────────┐
                                                                          ▼
                       version selection ─► nightly pricing ─► comparison ─► findings ─► routing
                       (deterministic)       (Decimal)          (tolerance)              │
                                                                                         ▼
                                LLM narrative + supplier draft ─► number-grounding check ─► case
                                (optional; falls back to template)                        │
                                                                                          ▼
                                     action proposal ─► human approval ─► SIMULATED execution ─► outcome + audit log
```

## Components (backend/app)

| Module | Responsibility | LLM? |
|---|---|---|
| `config.py` | Settings from env; startup validation of provider credentials | – |
| `providers/` | `LLMProvider` protocol; `OpenAIProvider`, `GroqProvider`, `OracleProvider` (ground-truth replay for demo/eval), `ScriptedProvider` (tests); timeouts, bounded retries, typed errors, usage + cost | – |
| `domain.py` | Pydantic schemas: contract extraction, booking, findings, routes | – |
| `pipeline/extraction.py` | Prompt, schema, validation, evidence verification | yes |
| `pipeline/injection.py` | Pattern scan of untrusted text for instruction-like content | no |
| `pipeline/engine.py` | Version selection, night-by-night pricing, cancellation fees, findings, routing | no |
| `pipeline/narrative.py` | Explanation + supplier email draft; rejects drafts citing numbers absent from facts | yes (optional) |
| `actions.py` | Action state machine + audit trail | no |
| `db.py`, `api.py` | SQLAlchemy (SQLite default, any SQLAlchemy URL) and FastAPI routes | – |
| `evals/` | Dataset generator, runner, comparison | – |

Frontend (`frontend/`): Next.js + TypeScript + Tailwind; calls the FastAPI JSON API.

## Key trade-offs

- **LLM extracts, code decides.** The model never computes amounts or chooses routes. Every rate it returns must carry a verbatim quote. Quotes not found in the source mark the value *unverified*, and any finding that depends on an unverified value is escalated.
- **Injection handling is defence-in-depth.** Documents go to the model inside delimiters and are labelled as data. The model has no tools. A deterministic scanner flags instruction-like text, and flagged cases cannot auto-clear.
- **No vector DB, broker, or agent framework.** A case is a single bounded document set (one hotel's contract versions), so there is nothing to retrieve, and the workflow is a linear typed pipeline with one human checkpoint. Background processing is synchronous: a case takes about 1 LLM call plus an optional narrative call.
- **SQLite by default.** The demo needs no infrastructure. SQLAlchemy keeps Postgres one `DATABASE_URL` away. Tables are created with `create_all` instead of Alembic for the MVP (see DECISIONS.md).
- **Oracle provider.** It replays the dataset's ground-truth extraction, so the demo and CI run with no API keys. It is always labelled `oracle` in results and the UI, and is never presented as model output.
