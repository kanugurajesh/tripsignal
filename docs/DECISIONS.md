# Decisions

Each entry records what was decided, why, the evidence, and the trade-offs.

## D1 — Primary workflow: contract rate assurance (not check-in recovery)
- **What:** Build booking and invoice auditing against digitized hotel contracts. Check-in exception recovery is deferred.
- **Why:** Flyo's Contract Agent already *digitizes* contracts. Auditing bookings against those terms is the next step and recovers money directly. Flyo already says it "flags failures" for check-in, so differentiation there is weaker.
- **Evidence:** flyo.ai homepage and agents section, About page, Web Check-in API docs (see PRODUCT_RESEARCH.md).
- **Trade-off:** The Check-in API's schema is public and well documented, while the contract inputs here are my own design and may differ from Flyo's internal schema.

## D2 — LLM reads, code decides
- **What:** The LLM only produces structured extraction with verbatim quotes and, optionally, a narrative. Version selection, pricing, comparison, routing, and state transitions are deterministic Python.
- **Why:** Arithmetic and policy must be exact and testable. Any money result an LLM computed would be unverifiable.
- **Consequence:** If extraction is wrong, the error is caught by quote/value verification, or else it propagates to the amount. That is why extraction is measured on its own in evals.

## D3 — Version rule: effective date ≤ booking date; partial amendments
- **What:** For each night, the newest document in force at the booking date that prices that room/meal/occupancy wins. Two documents with the same effective date that disagree produce VERSION_CONFLICT.
- **Why:** Rates are usually locked at booking. Amendments typically say "all other terms unchanged".
- **Trade-off:** Some contracts price by stay date instead. That would be a one-function change (`_applicable_groups`), but it is not configurable per contract today.

## D4 — Evidence verification: quote ⊂ source and value ∈ quote
- **What:** Normalized substring match, plus a check that the extracted number appears in its own quote.
- **Why:** This catches a model that quotes a real line but reports a different number. A test covers that case.
- **Trade-off:** Season dates and room names are not value-checked against the quote (date formats vary). This is listed in LIMITATIONS.

## D5 — Providers: official SDKs, chat.completions, strict json_schema
- **What:** OpenAI SDK 2.29 and Groq SDK 1.7 through one `ChatCompletionsProvider`. Defaults: `GROQ_MODEL=openai/gpt-oss-120b` (Groq lists it among the strict json_schema models) and `OPENAI_MODEL=gpt-6.1-sol` (OpenAI's mid-priced current model).
- **Capability differences handled explicitly:**
  - Groq strict mode only works on the listed models. Other models fall back to `json_object` mode with the schema in the prompt, plus Pydantic validation.
  - OpenAI gets no `temperature` parameter, because reasoning models reject it.
- **SDK retries are disabled.** One visible, tested retry policy handles timeouts, 429s, and 5xx errors. Quota, auth, and bad output are not retried.
- **Fallback is opt-in** (`FALLBACK_PROVIDER`). It triggers only on infrastructure errors and is recorded as `fallback_from`.

## D6 — SQLite + `create_all` (no Alembic, no Postgres requirement)
- **Why:** The local demo needs zero infrastructure. SQLAlchemy keeps Postgres one `DATABASE_URL` away.
- **Revisit when:** A schema change has to preserve existing data. Add Alembic at that point.

## D7 — No vector DB, queue, or agent framework
- **Why:** Each audit uses a handful of known documents for one hotel, so there is nothing to retrieve. Each audit is about one extraction call, cached per document hash. The flow is linear with one human checkpoint. LangGraph or Celery would add moving parts without solving a problem this MVP has.

## D8 — Oracle provider for demo and CI
- **What:** A provider that replays dataset ground truth, always labelled `oracle` in the API, UI, and results.
- **Why:** The repo must be runnable and testable without keys, and the engine must be evaluated independently of extraction quality.

## D9 — Change during implementation: quota errors are non-retryable
- **What changed:** I added `ProviderQuotaExhausted`, which is not retried.
- **Evidence:** The first real OpenAI run returned `429 insufficient_quota / credit_balance_exhausted` on every call. The retry loop was wasting attempts on an error that can never succeed.
- **Consequence:** I deleted that run's result file, because it measured billing state, not model quality.

## D10 — Change during implementation: Next.js 16 Cache Components
- **What changed:** The generated Next 16 app enables Cache Components by default, so client URL hooks (`usePathname`, `useParams`) must sit inside `<Suspense>`. The nav and the case view are wrapped accordingly.

## D12 — Traveller flow: price what happened, from the clause that governs it
- **What:** A booking now records what actually happened: `NO_SHOW` status, `actual_check_out` (earlier means early departure, later means extension), `extension_booked_on`, `stayed_room_type` and `upgrade_reason`. Contracts gain no-show, early-departure and upgrade clauses, extracted with verbatim quotes like every other term (`extract-v2`). Each billable night carries a basis (stay, extension, or a penalty), and the clauses used are returned with the result and quoted in the supplier email.
- **Rules:**
  - Each clause comes from the newest version in force on the booking date that states it, so an amendment can change the no-show penalty without restating the rates. Same-date versions that disagree raise VERSION_CONFLICT.
  - Extension nights are priced at the terms in force on `extension_booked_on`, because extending a stay is a new commitment made on that date. The original nights keep the booking-date terms.
  - Early-departure penalty nights are the first unused nights, capped at the number of unused nights.
  - A no-show is never priced from the cancellation clause unless that clause explicitly covers no-shows. If no clause covers it, the result is MISSING_POLICY_TERMS and REQUEST_INFO.
- **Why:** The feedback was to cover more of the traveller flow. These are the cases where supplier invoices most often drift from the contract: a full stay billed after a 2-night early departure, a no-show billed in full, an upgraded rate billed for a complimentary upgrade. The new code keeps the existing principle: a missing or unverified clause means abstain, never assume.
- **Trade-off:** Data contradictions (a no-show with a departure date, a room change with no reason) are MISSING_BOOKING_FIELD, not a separate code, so they reuse the existing information-request flow.

## D11 — Change after first Groq run: honour `retry-after` on 429
- **Evidence:** The first Groq run had 6/10 extractions fail with 429 under 1s/2s backoff. All failed safely (EXTRACTION_FAILED → escalate).
- **Change:** `ProviderRateLimited` carries the server's `retry-after`, and the retry loop waits at least that long (capped at 60s). A test covers this.
- **Result:** The rerun with `LLM_MAX_RETRIES=5 --workers 1` scored 102/102 routes correct with 100% extraction recall.
