# Limitations and unsupported assumptions

## Evaluation status (honest)
- **Groq (`openai/gpt-oss-120b`) has been evaluated end to end:** 102/102 routes correct and 0 unsafe auto-clears. **OpenAI has not:** the key returns `insufficient_quota`, so there is no provider comparison yet.
- Groq free-tier rate limits make a full run slow (retries wait for `retry-after`). Use `--workers 1`.
- Extraction quality is measured over only **10 contract documents** (7 hotels, 3 formatting styles). That is enough to exercise the pipeline, but too few to generalize about model quality. More document variants are the top dataset improvement.
- Expected outcomes are computed by the generator's own arithmetic from the scenario spec. It is independent of the engine's code, but it was written by the same author with the same rule interpretation (D3). A domain expert should review the rules.

## Product and domain
- Contracts are plain text. There is no PDF or OCR ingestion. "Unreadable" cases simulate OCR damage in text.
- Rates are per room per night only. There are no per-person rates, child or extra-bed supplements, meal supplements on top of room rates, promotions or early-bird discounts, allotments or release periods, taxes, or commissions.
- No FX: a currency mismatch always becomes REQUEST_INFO.
- Version rule: booking-date based (D3). Not configurable per contract.
- Season dates and room names extracted by the LLM are checked for quote presence, but not value-matched against the quote.
- Contract inputs are my own design. They are not Flyo's schema, and nothing here integrates with Flyo.

## Safety and operations
- **Auth is a demo stub.** Roles come from `X-Actor-Id` / `X-Actor-Role` headers. Role checks and segregation of duties are enforced server-side, but anyone can claim any role. Real deployment needs SSO/JWT.
- Supplier messages and credits are **simulated**. No email is sent. Credits are operator-reported and are not reconciled against credit notes.
- The injection scanner is pattern-based and can be evaded. It is one layer among several: data delimiting, no tools, quote verification, and no auto-clear on hits.
- SQLite, synchronous processing, and no migration tool (D6).
- Case IDs come from a row count, which is fine for a single-writer demo but not for concurrent writers.

## Not built (deferred)
- Check-in exception recovery on top of the Web Check-in API (candidate B in PRODUCT_RESEARCH.md).
- Re-audit linking (a corrected booking currently creates a new case, not a new version of the old one).
- Document upload UI (the API exists: `POST /api/documents`, `POST /api/audits`).
