# Security & AI-Safety Audit — JanSetu AI

Audit of every endpoint and AI path, performed before public evaluation. Findings and mitigations, all implemented in code.

## AI conversation safety

Scope guard: the NL→SQL classifier must return `{"off_topic": true}` for anything outside constituency civic data (coding, homework, general knowledge, role-change attempts); the server then returns a fixed redirect message translated to the user's language — the LLM never free-generates off-topic content. Applied on both Gemini and Groq paths. Anti-prompt-injection: system prompts instruct models to ignore instructions embedded in user questions and to treat grievance descriptions (citizen input) as untrusted data, never as instructions. Anti-hallucination: answer prompts require using only numbers present in query results and an explicit "no matching data found" on empty results; the briefing prompt forbids inventing counts, costs, or wards not in the supplied data.

## Injection & code-execution surfaces

SQL layer: SELECT/WITH-only; deny-list of 19 verbs/functions including `attach`, `pragma`, `load_extension`, `randomblob`/`zeroblob` (memory bombs); single-statement enforcement; 2,000-char cap; `PRAGMA query_only=ON` (hard read-only); progress-handler abort after ~2M VM steps (kills cartesian-join CPU DoS). XSS: all AI- and citizen-derived fields (ticket description, briefing rationale, letters, alerts) are HTML-escaped before rendering; chat messages use `textContent`. Language parameter: whitelisted against 12 known codes — unknown values can no longer be injected into prompts.

## Resource & cost protection

Per-IP rate limiting (40 req/min, sliding window, HTTP 429). Photo uploads: image/* MIME check, 8 MB cap read-limited server-side. Question length capped (400 chars), notes (500 chars), grievance descriptions (500 chars). LLM prompt payloads bounded (≤30 rows, strings truncated to 120 chars). Briefing responses cached 10 min per language; `/api/diag` cached 60s. `/api/letter` whitelists and truncates work fields — arbitrary client JSON never reaches the LLM.

## Access & data

Optional office authentication (`OFFICE_KEY` → `X-Office-Key`) on briefing/letter endpoints; citizen intake deliberately open. Ward values validated against the known ward list on insert. No PII collected (no Aadhaar, name, address); dataset fully synthetic; DPDP-aligned consent screen; India data residency (asia-south1). The Maps browser key is public by design (all client-side map keys are visible to the browser) and is protected by HTTP-referrer restriction and an API allow-list in Google Cloud, plus daily quota caps so it cannot be abused for cost.

## Consciously accepted risks (hackathon scope)

These are known trade-offs, documented rather than hidden:

- The demo database is fully synthetic and public, so read-only data exposure is not sensitive.
- The rate limiter and diagnostic/briefing caches are in-memory (per-instance) — adequate for a single-instance prototype; a production deployment would use a shared store such as Redis.
- The office key, when enabled, is held in browser `localStorage`; production would use signed session cookies.
- BigQuery and Cloud Translation are integrated but optional; the default SQLite path keeps the prototype runnable with zero cloud dependencies.

## Reporting

This is a hackathon prototype. For any security concern, please open a GitHub issue on the repository.