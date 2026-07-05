# JanSetu AI 🇮🇳 — MPLADS Decision Copilot for Constituency Development

### 🔗 [**LIVE DEMO — click to open the platform**](https://REPLACE-WITH-CLOUD-RUN-URL.run.app) · no login needed · works on mobile

> For evaluators: the demo storyline — open **Dashboard** (see the SC/ST compliance breach and streetlight spike alerts) → **Demand Hotspots** map (same wards glowing) → **Priority Works** (AI converts demand + idle funds into ranked sanctionable works; click "Draft recommendation letter") → **Report/Suggest** (photo → AI-classified ticket) → try voice in Hindi via the 🎙️ button.

**Track 1: People's Priorities** — Build with AI: Code for Communities Hackathon 2026

**The problem:** ₹1,729 crore of MPLADS funds sit unspent nationally; only ~53% of released funds have been utilised since 2019, and 62% of MPs miss the mandatory 22.5% SC/ST-area allocation. Existing tools collect complaints (CPGRAMS, Swachhata) or track works after sanction (e-SAKSHI). **Nothing helps an MP's office decide *which* works to sanction.** JanSetu ("bridge to the people") is that missing decision layer.

## What it does

**Citizens (inclusive by design):** report issues or suggest works by **photo** (Gemini Vision auto-classifies category, department, severity), **voice** (no literacy or typing needed), or text. Works **offline** — reports queue on-device and sync when signal returns. Every response is also read aloud.

**Language support (stated precisely):** voice *input* in 12 Indian languages (on-device Web Speech API); chat *responses* in the user's language via Gemini's native multilingual generation plus a server-side translation chain (**Cloud Translation API → Gemini → Groq**) that also localises Lite-engine answers and briefing summaries; text-to-speech *output* with automatic script detection across 11 Indian scripts. Formal DA letters remain in English by design (official correspondence).

**The MP's office:**
- 💬 **Ask anything in natural language** (any Indian language): Gemini converts questions to SQL over grievances, ward demographics, and the fund ledger, and answers with charts
- 🗺️ **Demand hotspot map** — ward-level open-issue intensity with demographic profiles (Google Maps Platform, Leaflet/OSM fallback)
- 🚨 **Spike alerts** — statistical anomaly detection per ward × category
- ⚖️ **Compliance radar** — live tracking of SC/ST 22.5% mandate and unspent balance
- 🎯 **Priority Works briefing** — Gemini fuses citizen demand, spikes, ward demographics (population, SC/ST %, schools, PHCs), and the MPLADS ledger into ranked, costed, *compliant* sanctionable works — each with a **one-click draft recommendation letter** to the District Authority

## Architecture

```
Citizen / MP office (PWA: voice 12 langs + photo + chat + offline queue)
        │
        ▼
FastAPI on Cloud Run (asia-south1) ──── Gemini 2.0 Flash
        │        • NL→SQL (guard-railed, read-only)   • photo → structured ticket
        │        • priority-works synthesis           • DA letter drafting
        ▼
SQLite (prototype) → BigQuery (scale path; single-file data layer swap)
Google Maps Platform (hotspots) · Web Speech API (STT/TTS, on-device offline packs)
```

## Quick start

```bash
pip install -r requirements.txt
python data/generate_data.py            # builds jansetu.db (~2,800 grievances, wards, fund ledger)
export GEMINI_API_KEY=your_key          # aistudio.google.com (primary AI)
export MAPS_API_KEY=your_maps_js_key    # optional; falls back to OpenStreetMap
export GROQ_API_KEY=your_groq_key       # optional free fallback LLM tier
uvicorn app.main:app --reload           # open http://localhost:8000
```

## Always-functional by design (graceful degradation)

Every AI call tries providers in order — **Gemini → Groq (free tier) → built-in Lite engine** — falling through at runtime on quota exhaustion, key restrictions, or network failure. The Lite engine is fully offline-capable: keyword-template NL queries, rule-based work ranking, keyword photo triage, and template letters. Maps degrade Google Maps → OpenStreetMap; voice uses the free on-device Web Speech API. Whenever a fallback engages, the UI shows an information notice stating which provider changed and that **core features are unaffected** — the header chip always shows the active AI provider. The app is therefore functional with zero API keys.

## Deploy (Google Cloud Run — mandatory Google deploy path)

```bash
gcloud run deploy jansetu --source . --region asia-south1 \
  --set-env-vars GEMINI_API_KEY=$GEMINI_API_KEY,MAPS_API_KEY=$MAPS_API_KEY \
  --allow-unauthenticated
```

## BigQuery mode (constituency-scale analytics)

The NL→SQL analytics path can run on **BigQuery** instead of SQLite:

```bash
pip install google-cloud-bigquery pandas pyarrow
python scripts/load_bigquery.py --project YOUR_PROJECT --dataset jansetu
export USE_BIGQUERY=1 BQ_PROJECT=YOUR_PROJECT BQ_DATASET=jansetu
```

Bare table names in generated SQL are mapped to the BigQuery dataset automatically; if BigQuery is unreachable the query falls back to SQLite (same degradation philosophy as the AI layer).

## Privacy, security & responsible AI

No Aadhaar, name, caste, or exact address collected; in-app consent screen (DPDP Act 2023-aligned); India data residency (asia-south1); read-only guard-railed SQL layer (prompt-injection defense); per-IP rate limiting (40 req/min); optional office authentication (`OFFICE_KEY` env → `X-Office-Key` header protects briefing/letter endpoints — left open in demo mode for judges); AI recommendations are advisory and traceable — the MP's office decides.

## Scalability & impact

One Lok Sabha constituency ≈ 25 lakh citizens; 543 constituencies. Stateless Cloud Run autoscaling; onboarding a new constituency = load its grievance export + ward data, redeploy: under a day.

## Repo layout

```
data/generate_data.py    synthetic dataset: grievances + ward demographics + MPLADS ledger
app/main.py              FastAPI routes
app/gemini.py            Gemini calls (NL→SQL, vision, briefing, letters) + mock mode
app/db.py                data layer (SQLite now, BigQuery-ready), anomaly + compliance logic
app/static/              PWA: index.html, sw.js, manifest.json
pitch/                   pitch deck + project write-up
```

## Citations (data, APIs, components)

- **AI:** [Gemini API](https://ai.google.dev/) (gemini-2.0-flash) via Google AI Studio
- **Maps:** [Google Maps Platform JS API](https://developers.google.com/maps); fallback [Leaflet](https://leafletjs.com/) (BSD-2) + [OpenStreetMap](https://www.openstreetmap.org/copyright) tiles (ODbL)
- **Charts:** [Chart.js](https://www.chartjs.org/) (MIT)
- **Backend:** [FastAPI](https://fastapi.tiangolo.com/) (MIT), [Uvicorn](https://www.uvicorn.org/) (BSD-3)
- **Voice:** Browser Web Speech API (built-in)
- **Dataset:** fully **synthetic**, generated by `data/generate_data.py`; no personal data. Category taxonomy inspired by public [CPGRAMS](https://pgportal.gov.in/)/[Swachhata](https://swachhata.gov.in/) schemas; MPLADS fund/compliance framing per [MPLADS guidelines (MoSPI)](https://www.mplads.gov.in/) and reported utilization statistics
- Problem statistics: MPLADS utilization reporting, [Drishti IAS summary](https://www.drishtiias.com/daily-updates/daily-news-analysis/member-of-parliament-local-area-development-scheme)

## License

MIT. Built entirely during the hackathon event window.
