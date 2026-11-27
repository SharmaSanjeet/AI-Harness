import os

# Same NO_PROXY "[::1]" workaround as the other labs — set before any localhost HTTP client.
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["no_proxy"] = "localhost,127.0.0.1"

import re
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

import fin
import fin_db
from agent import analyze_company

app = FastAPI(title="LedgerLens — Financial Analysis Agent", version="1.0.0")

STATIC_DIR = Path(__file__).resolve().parent / "static"
ENABLE_ADMIN_RESET = os.getenv("ENABLE_ADMIN_RESET", "true").lower() != "false"
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

_SAFE_TOKEN = re.compile(r"[^A-Za-z0-9._@ -]")


def _clean(value: str, max_len: int = 64) -> str:
    """Strip input to a safe charset/length before it reaches SQL or the LLM."""
    return _SAFE_TOKEN.sub("", value or "").strip()[:max_len]


class AnalyzeRequest(BaseModel):
    ticker: str
    prepared_by: str = "analyst-bot"


class PublishRequest(BaseModel):
    reviewer: str = "senior_analyst@company.com"


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    """Liveness/readiness probe: database is required, Ollama is optional
    (the advisor degrades to rule-built narratives when unreachable)."""
    db_ok = False
    try:
        with fin_db.engine.begin() as con:
            con.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass
    ollama_ok = False
    try:
        requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=2)
        ollama_ok = True
    except Exception:
        pass
    ok = db_ok
    return JSONResponse(status_code=200 if ok else 503,
                        content={"ok": ok, "checks": {"database": db_ok, "ollama": ollama_ok}})


@app.get("/companies")
def companies_all():
    return {"items": fin.list_companies()}


@app.get("/companies/{ticker}")
def company_one(ticker: str):
    ticker = _clean(ticker, 8).upper()
    company = fin.get_company(ticker)
    if not company:
        raise HTTPException(404, f"Ticker '{ticker}' not found")
    statements = fin.get_statements(ticker)
    return {**company,
            "statements": statements,
            "ratios": fin.compute_ratios(statements)}


@app.post("/analyze")
def analyze(request: AnalyzeRequest):
    ticker = _clean(request.ticker, 8).upper()
    prepared_by = _clean(request.prepared_by) or "analyst-bot"
    if not ticker:
        return {"ok": False, "error": "Please provide a ticker."}
    return analyze_company(ticker, prepared_by)


@app.post("/briefs/{brief_id}/publish")
def publish(brief_id: int, request: PublishRequest):
    reviewer = _clean(request.reviewer) or "senior_analyst@company.com"
    return fin.publish_brief(brief_id, reviewer)


@app.get("/briefs/open")
def open_briefs():
    return {"items": fin.list_open_briefs()}


@app.get("/briefs/recent")
def recent_briefs(limit: int = 12):
    return {"items": fin.list_recent_briefs(max(1, min(limit, 50)))}


@app.post("/admin/reset")
def admin_reset():
    if not ENABLE_ADMIN_RESET:
        raise HTTPException(403, "Admin reset is disabled in this deployment "
                                 "(set ENABLE_ADMIN_RESET=true to enable).")
    fin_db.reset_demo_data()
    return {"ok": True,
            "message": "Demo data reset — companies and statements reseeded, brief history cleared."}


fin_db.init_db()
