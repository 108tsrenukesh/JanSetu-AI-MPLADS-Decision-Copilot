"""JanSetu AI - FastAPI backend."""
import os

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, gemini

app = FastAPI(title="JanSetu AI")

STATIC = os.path.join(os.path.dirname(__file__), "static")


class AskRequest(BaseModel):
    question: str


@app.get("/api/health")
def health():
    return {"ok": True, "mock_mode": gemini.MOCK,
            "engine": "lite" if gemini.MOCK else "gemini"}


@app.post("/api/ask")
def ask(req: AskRequest):
    return gemini.ask(req.question)


@app.get("/api/dashboard")
def dashboard():
    stats = db.summary_stats()
    stats["anomalies"] = db.detect_anomalies()
    return stats


@app.get("/api/briefing")
def briefing():
    return gemini.priority_briefing()


@app.get("/api/hotspots")
def hotspots():
    return db.hotspots()


@app.get("/api/funds")
def funds():
    return db.fund_status()


@app.post("/api/letter")
def letter(work: dict):
    return gemini.draft_letter(work)


@app.post("/api/report")
async def report(photo: UploadFile = File(...), ward: str = Form(...), note: str = Form("")):
    data = await photo.read()
    return gemini.classify_photo(data, photo.content_type or "image/jpeg", note, ward)


@app.get("/api/config")
def config():
    return {"maps_api_key": os.environ.get("MAPS_API_KEY", ""), "mock_mode": gemini.MOCK}


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC), name="static")
