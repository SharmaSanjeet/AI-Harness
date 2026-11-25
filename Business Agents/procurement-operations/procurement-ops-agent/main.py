import os

# Same NO_PROXY "[::1]" workaround as the other labs — set before any localhost HTTP client.
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["no_proxy"] = "localhost,127.0.0.1"

import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import ops
import ops_db
from agent import assess_and_draft

app = FastAPI(title="Procurement & Operations Agent", version="1.0.0")

STATIC_DIR = Path(__file__).resolve().parent / "static"

_SAFE_TOKEN = re.compile(r"[^A-Za-z0-9._@ -]")


def _clean(value: str, max_len: int = 64) -> str:
    """Strip input to a safe charset/length before it reaches SQL or the LLM."""
    return _SAFE_TOKEN.sub("", value or "").strip()[:max_len]


class AssessRequest(BaseModel):
    sku: str
    requested_by: str = "ops-bot"


class ApproveRequest(BaseModel):
    approver: str = "manager@company.com"


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/inventory")
def inventory_all():
    return {"items": ops.list_inventory()}


@app.get("/inventory/{sku}")
def inventory_one(sku: str):
    item = ops.inventory_status(ops.get_inventory(sku))
    if not item:
        raise HTTPException(404, f"SKU '{sku}' not found")
    return item


@app.post("/assess")
def assess(request: AssessRequest):
    sku = _clean(request.sku, 24).upper()
    requested_by = _clean(request.requested_by) or "ops-bot"
    if not sku:
        return {"ok": False, "error": "Please provide a SKU."}
    return assess_and_draft(sku, requested_by)


@app.post("/approve/{pr_id}")
def approve(pr_id: int, request: ApproveRequest):
    approver = _clean(request.approver) or "manager@company.com"
    return ops.approve_pr(pr_id, approver)


@app.get("/pr/open")
def open_prs():
    return {"items": ops.list_open_pr()}


@app.get("/pr/recent")
def recent_prs(limit: int = 12):
    return {"items": ops.list_recent_pr(max(1, min(limit, 50)))}


@app.post("/admin/reset")
def admin_reset():
    ops_db.reset_demo_data()
    return {"ok": True,
            "message": "Demo data reset — inventory and vendors reseeded, PR history cleared."}


ops_db.init_db()
