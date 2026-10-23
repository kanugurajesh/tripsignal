# Product Research — Flyo AI

Research date: 2026-10-20. Sources are Flyo's public pages and docs, read on that date. Anything not stated in a source is marked as an **assumption**.

## 1. What Flyo does

Flyo (FLYO TECHNOLOGIES PRIVATE LIMITED, Bangalore) sells AI agents for travel businesses. The agents run inside a company's existing email, WhatsApp, and airline or supplier workflows, and the homepage says there is "no separate dashboard". The About page says the company focuses on **post-booking** servicing and operations, because it sees that as where much of the revenue and service quality comes from.

| Agent / product (as publicly named) | Publicly described capability |
|---|---|
| Query & Quotation Agent | Connects mail and WhatsApp, screens lead intent, finds quotes, requests rates from DMCs, sends reminders |
| **Contract Agent** | Analyzes hotel and supplier contracts, digitizes contracts from email, and flags gaps, changes, and renewal dates |
| Post-Booking Agent | Consolidates tickets, builds trip calendars, does web check-in, and sells ancillaries (lounge, insurance, eSIM) |
| Webcheckin Agent / Web Check-in API | Automated airline web check-in, boarding passes sent over WhatsApp, failures flagged before departure. Public API docs exist |
| Website Builder | No-code agency site and shareable itineraries |
| Finance Agent | Named only in third-party listings (Capterra/GetApp). Flyo's own site does not describe it |

**Segments:** independent travel agents, DMCs, TMCs, OTAs, and enterprises. Businesses under 300 bookings a month are directed to a self-serve portal.

**Public metrics, all claimed by Flyo and not verified here:** 70+ agencies, 100,000+ trips a year, 60,000+ check-ins in the last six months, 500+ airlines, and 99.9% uptime.

**Web Check-in API (documented):** four endpoints (`/subscribe`, `/update`, `/status`, `/requests`) and an `X-API-Key` header. Statuses are SCHEDULED, IN_PROGRESS, COMPLETED, FAILED, and CANCELLED, plus a `missing_info[]` list. Webhook events can be duplicated or arrive out of order (dedupe by `event_id`). A 6-hour departure cutoff applies, and COMPLETED can occur without a boarding pass.

## 2. Problems Flyo already appears to address

- Lead-to-quote handling (Query & Quotation Agent)
- Contract digitization and renewal or gap flags (Contract Agent)
- Check-in automation and failure flagging (Webcheckin Agent and API)
- Ancillary upsell (Post-Booking Agent)

I have **not** assumed any of these lacks a feature just because I did not find it in public material.

## 3. Candidate opportunities (complementary to Flyo's public products)

Scores run 1–5, higher is better. "Data" means whether realistic synthetic data can be built honestly. "Eval" means whether correctness can be checked deterministically.

| # | Opportunity | Impact | Flyo relevance | Feasibility | Data | Differentiation | Eval | Total |
|---|---|---|---|---|---|---|---|---|
| A | **Contract-to-booking rate assurance**: check bookings and supplier invoices against the digitized contract version that applies, and recover overcharges | 5 (direct money recovery) | 5 (the next step after the Contract Agent's digitization; fits the "Finance Agent" theme) | 4 | 5 | 4 | 5 | **28** |
| B | Check-in exception recovery queue: triage Web Check-in API failures, MISSING_INFO, and 6-hour cutoff risk; draft traveller requests | 4 | 5 (the API is documented) | 4 | 4 | 2 (Flyo already "flags failures") | 5 | 24 |
| C | Supplier invoice reconciliation without contracts (booking vs. invoice only) | 4 | 3 | 5 | 5 | 2 | 5 | 24 |
| D | Ancillary opportunity detection | 3 | 4 | 3 | 2 (conversion data would have to be invented) | 2 (Post-Booking Agent already does this) | 2 | 16 |
| E | Incomplete enquiry and quotation detection | 3 | 4 | 4 | 3 | 2 (Query Agent overlaps) | 3 | 19 |

## 4. Selected scope: A — Contract Rate Assurance

**Why A:**

1. **It complements Flyo's products without duplicating them.** Flyo says its Contract Agent *digitizes* contracts and flags gaps and renewals. Using those digitized terms to *audit* every booking and invoice is the next step, and it turns digitized data into recovered money.
2. **The money is explicit and measurable.** The comparison is deterministic arithmetic: contracted rate × nights × rooms, minus the invoiced amount. Every value traces back to source text.
3. **The LLM does a real job.** Supplier contracts are semi-structured prose. Amendments, seasons, and cancellation clauses vary in wording. Extraction with source quotes is a language task, and the arithmetic is not.
4. **It can be evaluated honestly.** Synthetic contracts are generated with known ground truth, so extraction, discrepancy detection, routing, and amounts can all be asserted deterministically.
5. **There are real safety cases.** Conflicting amendments, unreadable OCR, currency mismatches, and prompt injection in supplier documents all have a right answer: abstain or escalate.

**Complementary workflow (B):** deferred. It is a good second workflow because the API schema is public, but building A well comes first. See `LIMITATIONS.md`.

## 5. Assumptions and unknowns

- **Assumption:** Contracts arrive as text, from email bodies or PDFs already converted to text. The MVP does not do PDF or OCR parsing. "Unreadable" cases simulate OCR damage in text.
- **Assumption:** Rates in force are those of the latest contract version whose effective date is on or before the **booking date**. Some contracts instead price by stay date, so the rule is configurable in code and documented in `DECISIONS.md`.
- **Unknown:** Flyo's internal contract schema, the Contract Agent's API, and whether Flyo already does rate auditing internally. The MVP's inputs are defined independently and do not claim to match Flyo's.
- **Unknown:** Real discrepancy rates in the industry. No impact figures are claimed. The UI shows only *detected exposure on synthetic data*.
- All hotels, suppliers, bookings, and contracts are synthetic.

## 6. Sources

- https://www.flyo.ai/ (homepage, agents section)
- https://www.flyo.ai/en/about
- https://www.flyo.ai/en/web-check-in-api
- https://www.flyo.ai/en/api-docs
- Third-party listing (the "Finance Agent" mention): https://www.capterra.in/software/1112480/flyo-agent-portal
- Provider docs: https://console.groq.com/docs/structured-outputs, https://console.groq.com/docs/models, https://developers.openai.com/api/docs/models, https://developers.openai.com/api/docs/guides/structured-outputs
