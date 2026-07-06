"""JanSetu AI - FastAPI backend."""
import os
import time
from collections import defaultdict, deque

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, gemini

app = FastAPI(title="JanSetu AI")

STATIC = os.path.join(os.path.dirname(__file__), "static")

# Optional office authentication: set OFFICE_KEY to require an X-Office-Key
# header on office endpoints (briefing/letter). Unset = open demo mode.
OFFICE_KEY = os.environ.get("OFFICE_KEY", "")

# Simple in-memory rate limiter: max 40 requests/min per IP on /api/*.
_hits = defaultdict(deque)
RATE_LIMIT, RATE_WINDOW = 40, 60


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        ip = request.client.host if request.client else "?"
        q = _hits[ip]
        now = time.time()
        while q and now - q[0] > RATE_WINDOW:
            q.popleft()
        if len(q) >= RATE_LIMIT:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Rate limit exceeded — try again in a minute."},
                                status_code=429)
        q.append(now)
    return await call_next(request)


def _check_office(request: Request):
    if OFFICE_KEY and request.headers.get("X-Office-Key") != OFFICE_KEY:
        raise HTTPException(401, "Office key required")


class AskRequest(BaseModel):
    question: str
    lang: str = "en-IN"


@app.get("/api/health")
def health():
    return {"ok": True, "mock_mode": gemini.MOCK,
            "engine": "lite" if gemini.MOCK else "gemini"}


@app.post("/api/ask")
def ask(req: AskRequest):
    return gemini.ask(req.question, req.lang)


@app.get("/api/dashboard")
def dashboard():
    stats = db.summary_stats()
    stats["anomalies"] = db.detect_anomalies()
    return stats


@app.get("/api/briefing")
def briefing(request: Request, lang: str = "en-IN"):
    _check_office(request)
    return gemini.priority_briefing(lang)


@app.get("/api/hotspots")
def hotspots():
    return db.hotspots()


@app.get("/api/funds")
def funds():
    return db.fund_status()


@app.post("/api/letter")
def letter(work: dict, request: Request):
    _check_office(request)
    return gemini.draft_letter(work)


@app.post("/api/report")
async def report(photo: UploadFile = File(...), ward: str = Form(...), note: str = Form("")):
    data = await photo.read()
    return gemini.classify_photo(data, photo.content_type or "image/jpeg", note, ward)


@app.get("/api/diag")
def diag():
    """Live diagnostic: tests each AI tier and reports the raw error if any."""
    out = {"groq_key_set": bool(gemini.GROQ_KEY),
           "gemini_client": gemini._client is not None,
           "gemini_model": gemini.MODEL,
           "groq_models": getattr(gemini, "GROQ_MODELS", [])}
    try:
        out["groq_reply"] = gemini._groq_chat(
            [{"role": "user", "content": "Reply with the word OK"}])[:60]
    except Exception as e:
        out["groq_error"] = repr(e)[:400]
    try:
        out["gemini_reply"] = gemini._generate(["Reply with the word OK"])[:60] \
            if gemini._client else "no client"
    except Exception as e:
        out["gemini_error"] = repr(e)[:400]
    return out


@app.get("/api/config")
def config():
    return {"maps_api_key": os.environ.get("MAPS_API_KEY", ""), "mock_mode": gemini.MOCK}


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC), name="static")
