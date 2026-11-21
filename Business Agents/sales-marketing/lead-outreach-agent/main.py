import os

# Same NO_PROXY "[::1]" workaround as agent.py — set before any httpx-based import.
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["no_proxy"] = "localhost,127.0.0.1"

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

import crm
from agent import run_outreach

app = FastAPI(title="Sales & Marketing Automation Agent", version="1.0.0")

STATIC_DIR = Path(__file__).resolve().parent / "static"


class OutreachRequest(BaseModel):
    company: str


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/sales_email")
def sales_email(request: OutreachRequest):
    company = crm.sanitize_company(request.company)
    if not company:
        return {"error": "Please provide a company name."}
    return run_outreach(company)


@app.get("/activities")
def activities():
    return {"activities": list(reversed(crm.ACTIVITY_LOG))[:20]}
