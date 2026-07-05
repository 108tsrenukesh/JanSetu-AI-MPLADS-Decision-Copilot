# JanSetu AI — Pitch Deck Outline (10 slides)

Designed against the judging rubric: fitment, AI implementation (25%), deployment & scalability, inclusivity & accessibility (15%), real impact, presentation clarity.

1. **Title** — JanSetu AI (जनसेतु): Constituency Decision Intelligence. Team, track.
2. **The problem** — An MP's office receives thousands of grievances via phone, letters, walk-ins. No unified view. Issues surface only when they become crises. Planning "actionable works" is guesswork.
3. **The solution (one picture)** — Citizens report by photo/voice/text → AI structures everything → office asks questions in plain language → ranked Priority Works briefing. One diagram, no jargon (MP-friendly).
4. **Demo moment 1: the citizen** — Photo of garbage pile → Gemini Vision files ticket #2781: category, department, severity, description. Voice in Hindi works too. *Zero literacy required.*
5. **Demo moment 2: the office** — "Which wards had a spike this month?" → NL-to-SQL → answer + chart + spike alert: "Streetlights in Kisan Basti running 27× baseline."
6. **Demo moment 3: the decision** — Priority Works briefing: Top 7 ranked actions with rationale citing live numbers. This is the constituency plan.
7. **AI & architecture (25% of marks)** — Gemini 2.0 Flash: NL-to-SQL, multimodal triage, synthesis. FastAPI on Cloud Run. Guard-railed SQL layer. SQLite→BigQuery swap documented in one file.
8. **Inclusivity (15% of marks)** — Voice-first (hi-IN/en-IN), text-to-speech responses, photo reporting for non-readers, works on any smartphone browser, screen-reader friendly labels.
9. **Impact & scalability** — 1 constituency = ~25 lakh citizens. 543 constituencies. New constituency onboarding < 1 day (load grievance export, redeploy). Stateless Cloud Run autoscaling.
10. **Ask & roadmap** — Pilot with one MP office; WhatsApp intake channel; multilingual expansion (12 languages via Cloud Translation); CPGRAMS integration.

**Demo script (3 min):** slide 3 → live app: photo report (30s) → Hindi voice question (30s) → English question with chart (30s) → dashboard spike alerts (30s) → Priority Works briefing + read-aloud (45s) → close on impact numbers.
