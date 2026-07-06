"""AI layer with graceful degradation: Gemini first, free Lite engine fallback."""
import json
import os
import re
import time

from . import db

API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

_client = None
if API_KEY:
    try:
        from google import genai
        _client = genai.Client(api_key=API_KEY)
    except Exception:
        _client = None

MOCK = _client is None

# ---- Groq tier (free): OpenAI-compatible endpoint, no SDK needed ----
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
# Groq deprecates models over time; try candidates in order until one works.
GROQ_MODELS = [m for m in [
    os.environ.get("GROQ_MODEL", ""),
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "llama-3.3-70b-versatile",
    "gemma2-9b-it",
] if m]
GROQ_VISION_MODELS = [m for m in [
    os.environ.get("GROQ_VISION_MODEL", ""),
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
] if m]
_groq_working_model = None  # cache the first model that responds


def _groq_call_once(messages, model):
    import urllib.request
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps({"model": model, "messages": messages,
                         "temperature": 0.2}).encode(),
        headers={"Authorization": f"Bearer {GROQ_KEY}",
                 "Content-Type": "application/json",
                 "User-Agent": "JanSetuAI/1.0 (civic decision platform)"})
    with urllib.request.urlopen(req, timeout=40) as r:
        out = json.loads(r.read())
    text = out["choices"][0]["message"]["content"]
    if not text:
        raise RuntimeError("empty response")
    return text


def _groq_chat(messages, model=None):
    """Raises only if every candidate model fails."""
    global _groq_working_model
    candidates = ([model] if model else
                  ([_groq_working_model] if _groq_working_model else []) + GROQ_MODELS)
    last = None
    for m in candidates:
        try:
            text = _groq_call_once(messages, m)
            if model is None:
                _groq_working_model = m
            return text
        except Exception as e:
            last = e  # deprecated/unknown model or transient error - try next
    raise last or RuntimeError("no Groq model available")


def _groq_generate(user_text, system=None, model=None):
    msgs = ([{"role": "system", "content": system}] if system else []) +            [{"role": "user", "content": user_text}]
    return _groq_chat(msgs, model)


def _groq_notice(reason):
    # Silent failover: the backup provider is still a full AI, so no user-facing
    # notice is needed. (Provider details remain visible in /api/diag for ops.)
    return ""


def _notice(reason):
    return ("AI services are temporarily busy — running in Lite mode. "
            "All core features remain available.")


# ---- Server-side translation: Cloud Translation API -> Gemini -> Groq -> original ----
TRANSLATE_KEY = os.environ.get("TRANSLATE_API_KEY", "") or os.environ.get("MAPS_API_KEY", "")

LANG_NAMES = {
    "en": "English", "hi": "Hindi", "bn": "Bengali", "ta": "Tamil", "te": "Telugu",
    "mr": "Marathi", "gu": "Gujarati", "kn": "Kannada", "ml": "Malayalam",
    "pa": "Punjabi", "or": "Odia", "ur": "Urdu",
}


def _lang_code(lang):
    """'hi-IN' -> 'hi'."""
    return (lang or "en").split("-")[0].lower()


def _cloud_translate(text, target):
    import urllib.request, urllib.parse
    req = urllib.request.Request(
        f"https://translation.googleapis.com/language/translate/v2?key={TRANSLATE_KEY}",
        data=urllib.parse.urlencode({"q": text, "target": target, "format": "text"}).encode(),
        headers={"User-Agent": "JanSetuAI/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        out = json.loads(r.read())
    return out["data"]["translations"][0]["translatedText"]


def translate_text(text, lang):
    """Translate text into the user's language. Never raises; returns
    (text, provider) where provider is '' when no translation happened."""
    code = _lang_code(lang)
    if code == "en" or not text:
        return text, ""
    name = LANG_NAMES.get(code, code)
    if TRANSLATE_KEY:
        try:
            return _cloud_translate(text, code), "google-translate"
        except Exception:
            pass
    if _client is not None:
        try:
            return _generate([f"Translate to {name}. Output ONLY the translation:\n{text}"]).strip(), "gemini"
        except Exception:
            pass
    if GROQ_KEY:
        try:
            return _groq_generate(f"Translate to {name}. Output ONLY the translation:\n{text}").strip(), "groq"
        except Exception:
            pass
    return text, ""  # graceful: English original


def _generate(parts, system=None):
    from google.genai import types
    cfg = types.GenerateContentConfig(system_instruction=system) if system else None
    resp = _client.models.generate_content(model=MODEL, contents=parts, config=cfg)
    if not resp.text:
        raise RuntimeError("empty response")
    return resp.text


def _extract_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else None


def _reason(e):
    s = str(e)
    if "429" in s or "quota" in s.lower() or "exhaust" in s.lower():
        return "free-tier quota reached"
    if "403" in s or "permission" in s.lower() or "api key" in s.lower():
        return "API key restriction"
    return "service unreachable"


SQL_SYSTEM = f"""You are a data analyst for an Indian MP's constituency office.
Convert the user's question (English or any Indian language) into ONE SQLite SELECT query.
{db.SCHEMA_DOC}
Rules: SELECT only. Always LIMIT 50 or fewer. Return JSON only:
{{"sql": "...", "chart": "bar"|"line"|"none", "x": "<col>", "y": "<col>"}}"""

ANSWER_SYSTEM = """You are JanSetu, an assistant for an Indian MP's constituency office.
Given a question and query results, answer in 2-4 short sentences, concrete and factual.
Answer in the same language the user asked in. Mention specific wards/numbers."""


def ask(question, lang="en-IN"):
    lang_name = LANG_NAMES.get(_lang_code(lang), "English")
    if _client is None:
        return _lite_ask(question, "no API key configured", lang)
    try:
        plan = _extract_json(_generate([f"Question: {question}"], system=SQL_SYSTEM)) or {}
        sql = plan.get("sql", "")
        cols, rows = db.run_query(sql)
        answer = _generate(
            [f"Question: {question}\nRespond in {lang_name} (or the question's own language if different).\n"
             f"SQL: {sql}\nResults (JSON): {json.dumps(rows[:50], default=str)}"],
            system=ANSWER_SYSTEM)
        return {"answer": answer.strip(), "sql": sql, "rows": rows,
                "chart": plan.get("chart", "none"), "x": plan.get("x"), "y": plan.get("y"),
                "engine": "gemini", "notice": ""}
    except ValueError as e:
        return {"answer": f"I couldn't run that query safely ({e}). Try rephrasing.",
                "sql": "", "rows": [], "chart": "none", "engine": "gemini", "notice": ""}
    except Exception as e:
        if GROQ_KEY:
            try:
                return _groq_ask(question, _reason(e), lang)
            except Exception:
                pass
        return _lite_ask(question, _reason(e), lang)


def _groq_ask(question, reason, lang="en-IN"):
    lang_name = LANG_NAMES.get(_lang_code(lang), "English")
    plan = _extract_json(_groq_generate(f"Question: {question}", system=SQL_SYSTEM)) or {}
    sql = plan.get("sql", "")
    cols, rows = db.run_query(sql)
    answer = _groq_generate(
        f"Question: {question}\nRespond in {lang_name} (or the question's own language if different).\n"
        f"SQL: {sql}\nResults (JSON): {json.dumps(rows[:50], default=str)}",
        system=ANSWER_SYSTEM)
    return {"answer": answer.strip(), "sql": sql, "rows": rows,
            "chart": plan.get("chart", "none"), "x": plan.get("x"), "y": plan.get("y"),
            "engine": "groq", "notice": _groq_notice(reason)}


_LITE_TEMPLATES = [
    (r"unspent|fund|mplads|money|पैसा|फंड|खर्च",
     "MPLADS fund position by year",
     "SELECT year, allocated_lakh, sanctioned_lakh, spent_lakh, ROUND(allocated_lakh-spent_lakh,1) AS unspent_lakh FROM mplads_funds ORDER BY year",
     "bar", "year", "unspent_lakh",
     lambda rows: f"In {rows[-1]['year']}, Rs {rows[-1]['unspent_lakh']} lakh of the Rs {rows[-1]['allocated_lakh']} lakh MPLADS allocation is unspent." if rows else "No fund data."),
    (r"spike|surge|anomal|बढ़|उछाल",
     "Recent complaint spikes",
     "SELECT ward, category, COUNT(*) AS recent FROM grievances WHERE created_date>=date('now','-21 days') GROUP BY ward, category HAVING recent>=8 ORDER BY recent DESC LIMIT 10",
     "bar", "ward", "recent",
     lambda rows: f"The sharpest recent rise is {rows[0]['category']} in {rows[0]['ward']} ({rows[0]['recent']} complaints in 21 days)." if rows else "No significant spikes right now."),
    (r"sc[ /-]?st|dalit|adivasi|आरक्षित|अनुसूचित",
     "SC/ST wards and infrastructure",
     "SELECT ward, sc_st_pct, population, schools, phcs FROM wards WHERE sc_st_pct>=25 ORDER BY sc_st_pct DESC",
     "bar", "ward", "sc_st_pct",
     lambda rows: f"{len(rows)} wards have 25%+ SC/ST population, led by {rows[0]['ward']} ({rows[0]['sc_st_pct']}%). {rows[0]['ward']} has {rows[0]['schools']} schools and {rows[0]['phcs']} PHCs." if rows else "No SC/ST-majority wards found."),
    (r"slow|department|resolve|pending|देरी|विभाग",
     "Department resolution performance",
     "SELECT department, ROUND(AVG(julianday(resolved_date)-julianday(created_date)),1) AS avg_days FROM grievances WHERE status='resolved' AND created_date>=date('now','-180 days') GROUP BY 1 ORDER BY 2 DESC",
     "bar", "department", "avg_days",
     lambda rows: f"{rows[0]['department']} is slowest, averaging {rows[0]['avg_days']} days to resolve." if rows else "No resolution data."),
    (r"category|type|kind|श्रेणी",
     "Complaints by category (30 days)",
     "SELECT category, COUNT(*) AS n FROM grievances WHERE created_date>=date('now','-30 days') GROUP BY 1 ORDER BY 2 DESC",
     "bar", "category", "n",
     lambda rows: f"{rows[0]['category']} leads with {rows[0]['n']} complaints in the last 30 days." if rows else "No complaints logged."),
]

_LITE_DEFAULT = (
    "Open complaints by ward",
    "SELECT ward, COUNT(*) AS complaints FROM grievances WHERE status!='resolved' GROUP BY ward ORDER BY complaints DESC LIMIT 10",
    "bar", "ward", "complaints",
    lambda rows: f"{rows[0]['ward']} has the most open complaints ({rows[0]['complaints']})." if rows else "No open complaints.")


def _lite_ask(question, reason, lang="en-IN"):
    q = question.lower()
    for pat, title, sql, chart, x, y, fmt in _LITE_TEMPLATES:
        if re.search(pat, q):
            break
    else:
        title, sql, chart, x, y, fmt = _LITE_DEFAULT
    try:
        cols, rows = db.run_query(sql)
    except Exception:
        cols, rows = [], []
    answer, provider = translate_text(f"{title}: {fmt(rows)}", lang)
    return {"answer": answer, "sql": sql, "rows": rows,
            "chart": chart, "x": x, "y": y,
            "engine": "lite" + (f"+{provider}" if provider else ""),
            "notice": _notice(reason)}


VISION_SYSTEM = """You are a civic-issue triage system for an Indian constituency.
Look at the photo (and optional citizen note) and return JSON only:
{"category": one of ["Water Supply","Drainage & Sewage","Roads & Potholes","Streetlights","Garbage Collection","Electricity","Public Health","Stray Animals","Encroachment","Public Transport"],
 "department": one of ["Jal Board","Municipal Corporation","PWD","Electricity Board","District Health Office","Transport Dept"],
 "severity": "low"|"medium"|"high",
 "description": "one factual sentence describing the issue seen in the photo"}"""

_CAT_DEPT = {
    "Water Supply": "Jal Board", "Drainage & Sewage": "Municipal Corporation",
    "Roads & Potholes": "PWD", "Streetlights": "Electricity Board",
    "Garbage Collection": "Municipal Corporation", "Electricity": "Electricity Board",
    "Public Health": "District Health Office", "Stray Animals": "Municipal Corporation",
    "Encroachment": "Municipal Corporation", "Public Transport": "Transport Dept",
}

_NOTE_KEYWORDS = [
    (r"garbage|trash|waste|kachra|कचरा|कूड़ा", "Garbage Collection"),
    (r"pothole|road|sadak|सड़क|गड्ढ", "Roads & Potholes"),
    (r"drain|sewage|sewer|नाली|नाला", "Drainage & Sewage"),
    (r"water|paani|पानी|जल", "Water Supply"),
    (r"street ?light|lamp|बत्ती|लाइट", "Streetlights"),
    (r"power|electric|bijli|बिजली|तार", "Electricity"),
    (r"mosquito|dengue|health|डेंगू|मच्छर", "Public Health"),
    (r"dog|cattle|monkey|stray|कुत्त|गाय|बंदर", "Stray Animals"),
    (r"encroach|footpath|अतिक्रमण", "Encroachment"),
    (r"bus|auto|transport|बस", "Public Transport"),
]


def classify_photo(image_bytes, mime, note, ward):
    ticket, engine, notice = None, "gemini", ""
    if _client is None:
        engine, notice = "lite", _notice("no API key configured")
    else:
        try:
            from google.genai import types
            text = _generate([
                types.Part.from_bytes(data=image_bytes, mime_type=mime),
                f"Citizen note: {note or '(none)'}",
            ], system=VISION_SYSTEM)
            ticket = _extract_json(text)
        except Exception as e:
            if GROQ_KEY:
                try:
                    import base64
                    b64 = base64.b64encode(image_bytes).decode()
                    msgs = [
                        {"role": "system", "content": VISION_SYSTEM},
                        {"role": "user", "content": [
                            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                            {"type": "text", "text": f"Citizen note: {note or '(none)'}"}]}]
                    text = None
                    for vm in GROQ_VISION_MODELS:
                        try:
                            text = _groq_call_once(msgs, vm)
                            break
                        except Exception:
                            continue
                    ticket = _extract_json(text) if text else None
                    if ticket:
                        engine, notice = "groq", _groq_notice(_reason(e))
                except Exception:
                    ticket = None
            if ticket is None:
                engine, notice = "lite", _notice(_reason(e))
    if ticket is None:
        cat = "Garbage Collection"
        for pat, c in _NOTE_KEYWORDS:
            if note and re.search(pat, note.lower()):
                cat = c
                break
        ticket = {"category": cat, "department": _CAT_DEPT[cat], "severity": "medium",
                  "description": (note or "Civic issue reported via photo") +
                                 " (auto-classified by Lite engine; photo attached for manual review)"}
        if engine == "gemini":
            engine, notice = "lite", _notice("unexpected AI response")
    ticket.setdefault("department", _CAT_DEPT.get(ticket.get("category", ""), "Municipal Corporation"))
    gid = db.insert_grievance(ward=ward, category=ticket["category"],
                              department=ticket["department"],
                              description=ticket["description"],
                              severity=ticket.get("severity", "medium"), source="app-photo")
    ticket.update({"id": gid, "ward": ward, "engine": engine, "notice": notice})
    return ticket


BRIEFING_SYSTEM = """You are the MPLADS planning advisor to an Indian Member of Parliament.
You must convert citizen demand into SANCTIONABLE WORKS that use idle MPLADS funds
and fix compliance gaps. From the data below produce JSON only:
{"works": [{"rank": 1, "title": "...", "ward": "...",
            "rationale": "one sentence citing complaint counts / demographics",
            "department": "...", "urgency": "high"|"medium",
            "est_cost_lakh": <number>, "sc_st_ward": true|false,
            "fund_note": "one short phrase"}],
 "summary": "2-3 sentences: demand picture + fund position + compliance gap",
 "compliance_alert": "one sentence if SC/ST 22.5% mandate is unmet, else empty string"}
Rules: TOP 7 works; spikes and high-severity first; if SC/ST spend below 22.5% mandate
prioritise wards with sc_st_pct >= 25 (mark sc_st_ward=true); prefer infra-gap wards;
costs Rs 5-50 lakh each fitting unspent funds. Cite concrete numbers."""

_briefing_cache = {}  # lang -> {"t": ts, "data": {...}}
_CACHE_TTL = 600


def _gather_context():
    stats = db.summary_stats()
    anomalies = db.detect_anomalies()
    funds = db.fund_status()
    hot = db.hotspots()
    _, high_open = db.run_query("""SELECT ward, category, COUNT(*) AS n FROM grievances
        WHERE status!='resolved' AND severity='high'
        GROUP BY ward, category ORDER BY n DESC LIMIT 15""")
    return stats, anomalies, funds, hot, high_open


def _localise_briefing(out, lang):
    if _lang_code(lang) != "en":
        for key in ("summary", "compliance_alert"):
            if out.get(key):
                out[key], _ = translate_text(out[key], lang)
    return out


def priority_briefing(lang="en-IN"):
    now = time.time()
    cached = _briefing_cache.get(_lang_code(lang))
    if cached and now - cached["t"] < _CACHE_TTL:
        return cached["data"]
    stats, anomalies, funds, hot, high_open = _gather_context()
    if _client is not None:
        try:
            context = json.dumps({
                "anomalies": anomalies, "open_by_ward": stats["by_ward"][:10],
                "high_severity_open": high_open, "dept_performance": stats["dept_performance"],
                "fund_status": {k: funds[k] for k in
                                ("current_year", "unspent_lakh", "unsanctioned_lakh",
                                 "sc_st_pct_of_spend", "sc_st_mandate_pct", "sc_st_compliant",
                                 "sc_st_gap_lakh")},
                "sc_st_wards": funds["sc_st_wards"],
                "ward_profiles": [{k: w[k] for k in ("ward", "population", "sc_st_pct",
                                                     "schools", "phcs", "open_count", "high_count",
                                                     "top_category")} for w in hot["wards"]],
            }, default=str)
            out = _extract_json(_generate([f"Constituency data:\n{context}"], system=BRIEFING_SYSTEM))
            if not out or "works" not in out:
                raise RuntimeError("unexpected AI response")
            out.update({"anomalies": anomalies, "funds": funds, "engine": "gemini", "notice": ""})
            out = _localise_briefing(out, lang)
            _briefing_cache[_lang_code(lang)] = {"t": now, "data": out}
            return out
        except Exception as e:
            if GROQ_KEY:
                try:
                    out = _extract_json(_groq_generate(f"Constituency data:\n{context}",
                                                       system=BRIEFING_SYSTEM))
                    if out and "works" in out:
                        out.update({"anomalies": anomalies, "funds": funds,
                                    "engine": "groq", "notice": _groq_notice(_reason(e))})
                        return _localise_briefing(out, lang)
                except Exception:
                    pass
            return _localise_briefing(_lite_briefing(anomalies, funds, hot, high_open, _reason(e)), lang)
    return _localise_briefing(_lite_briefing(anomalies, funds, hot, high_open, "no API key configured"), lang)


def _lite_briefing(anomalies, funds, hot, high_open, reason):
    sc_wards = {w["ward"] for w in funds["sc_st_wards"]}
    ward_meta = {w["ward"]: w for w in hot["wards"]}
    works, used = [], set()

    def add(title, ward, rationale, dept, urgency, cost):
        works.append({"rank": len(works) + 1, "title": title, "ward": ward,
                      "rationale": rationale, "department": dept, "urgency": urgency,
                      "est_cost_lakh": cost, "sc_st_ward": ward in sc_wards,
                      "fund_note": f"fits within Rs {funds['unspent_lakh']} lakh unspent"})

    for a in anomalies[:3]:
        if len(works) >= 7:
            break
        add(f"Sanction {a['category'].lower()} restoration works in {a['ward']}", a["ward"],
            f"Complaint rate is {a['ratio']:.1f}x the 6-month baseline "
            f"({'SC/ST ward — counts toward the 22.5% mandate' if a['ward'] in sc_wards else 'sustained citizen demand'}).",
            "Municipal Corporation", "high", 18 + 6 * len(works))
        used.add(a["ward"])
    if not funds["sc_st_compliant"]:
        for w in funds["sc_st_wards"]:
            if len(works) >= 7 or w["ward"] in used:
                continue
            m = ward_meta.get(w["ward"], {})
            add(f"Community infrastructure works in {w['ward']} (SC/ST priority)", w["ward"],
                f"{w['sc_st_pct']}% SC/ST population with {m.get('schools','few')} schools and "
                f"{m.get('phcs',0)} PHCs for {w['population']//1000}k residents; "
                f"SC/ST spend is {funds['sc_st_pct_of_spend']}% vs the 22.5% mandate.",
                "Municipal Corporation", "high", 25)
            used.add(w["ward"])
    for h in high_open:
        if len(works) >= 7 or h["ward"] in used:
            continue
        add(f"Address high-severity {h['category'].lower()} backlog in {h['ward']}", h["ward"],
            f"{h['n']} unresolved high-severity {h['category']} complaints.",
            _CAT_DEPT.get(h["category"], "Municipal Corporation"), "medium", 12)
        used.add(h["ward"])
    return {"works": works,
            "summary": f"Rs {funds['unspent_lakh']} lakh unspent in {funds['current_year']}; "
                       f"SC/ST-area spend at {funds['sc_st_pct_of_spend']}% against the 22.5% mandate; "
                       f"{len(anomalies)} active complaint spikes. Ranked by the Lite engine "
                       f"(spikes → compliance gap → severity backlog).",
            "compliance_alert": "" if funds["sc_st_compliant"] else
                f"SC/ST-area spend is {funds['sc_st_pct_of_spend']}% — below the mandatory 22.5% under MPLADS. "
                f"Sanction approximately Rs {funds.get('sc_st_gap_lakh', 0)} lakh of works in SC/ST wards "
                f"this year to close the gap.",
            "anomalies": anomalies, "funds": funds,
            "engine": "lite", "notice": _notice(reason)}


LETTER_SYSTEM = """You draft formal MPLADS work recommendation letters from an MP's office
to the District Authority (District Magistrate), per MPLADS guidelines. Given a work item,
write a concise formal letter (under 200 words): subject line, work description, ward,
estimated cost in Rs lakh, justification citing citizen demand data, SC/ST note if relevant.
Sign as 'Office of the Member of Parliament, Rajpur Constituency'. Plain text."""


def draft_letter(work):
    if _client is not None:
        try:
            return {"letter": _generate([f"Work item JSON: {json.dumps(work, default=str)}"],
                                        system=LETTER_SYSTEM),
                    "engine": "gemini", "notice": ""}
        except Exception as e:
            reason = _reason(e)
            if GROQ_KEY:
                try:
                    return {"letter": _groq_generate(f"Work item JSON: {json.dumps(work, default=str)}",
                                                     system=LETTER_SYSTEM),
                            "engine": "groq", "notice": _groq_notice(reason)}
                except Exception:
                    pass
    else:
        reason = "no API key configured"
    letter = (
        "To: The District Magistrate, Rajpur District\n"
        f"Subject: Recommendation for sanction of work under MPLADS — {work.get('title', 'Development work')}\n\n"
        "Sir/Madam,\n\n"
        f"Under the Members of Parliament Local Area Development Scheme, the undersigned recommends "
        f"sanction of the following work in {work.get('ward', 'the constituency')}:\n\n"
        f"  Work: {work.get('title', '-')}\n"
        f"  Ward/Location: {work.get('ward', '-')}\n"
        f"  Estimated cost: Rs {work.get('est_cost_lakh', '-')} lakh\n"
        f"  Implementing department: {work.get('department', '-')}\n\n"
        f"Justification: {work.get('rationale', 'Documented citizen demand.')}\n"
        + ("This work is located in an SC/ST-majority area and counts toward the mandatory 22.5% "
           "allocation under the MPLADS guidelines.\n" if work.get("sc_st_ward") else "")
        + "\nKindly accord administrative sanction and initiate the work at the earliest.\n\n"
        "Office of the Member of Parliament, Rajpur Constituency")
    return {"letter": letter, "engine": "lite", "notice": _notice(reason)}
