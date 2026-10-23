# Plan — TripSignal: Contract Rate Assurance Agent

Scope selected in `docs/PRODUCT_RESEARCH.md`. One primary workflow. It audits hotel bookings and supplier invoices against the contract version that applies, explains each discrepancy using source evidence, and routes it to a gated recovery action.

## Slices
1. Domain schemas, deterministic engine, and engine tests
2. Provider abstraction (OpenAI and Groq), extraction with evidence verification, and provider tests
3. Dataset generator, eval runner, comparison CLI, and oracle baseline
4. Persistence, API, action state machine, audit trail, and API tests
5. Next.js dashboard: overview, queue, case detail with evidence, approvals, and evals
6. Real OpenAI eval run (key available). Groq is mock-tested only (no key)
7. README, LIMITATIONS, DECISIONS, Docker, and CI

## Acceptance criteria
- `pytest` passes with no network access and no keys
- `python -m evals.run --provider oracle` produces a results file with 100% route accuracy
- Case lifecycle works through the API: detect → propose action → approve or reject → simulated execute → record outcome. Unauthorized or invalid transitions return 4xx
- No auto-clear on injection, unverified evidence, version conflict, or missing data
- The UI shows the queue, the evidence beside each finding, and the approve flow end to end
- Switching providers happens only through `AI_PROVIDER`

## Status (2026-10-20)
Slices 1–5 and 7 are done. Slice 6: Groq evaluated (102/102 routes correct). OpenAI is blocked because the key returns `insufficient_quota`.

## Change log
- Quota errors are now non-retryable, after the first live run hit `insufficient_quota` (DECISIONS D9).
- Next 16 Cache Components required Suspense boundaries around URL hooks (D10).
- Seed is also used as the Docker entrypoint, so the demo is self-contained.
