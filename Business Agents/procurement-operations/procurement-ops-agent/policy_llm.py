import json
import os
import re

import requests
from dotenv import load_dotenv

# Same NO_PROXY "[::1]" workaround as main.py — set before any localhost HTTP call.
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["no_proxy"] = "localhost,127.0.0.1"

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")

COVER_DAYS_MAX = 90

PROC_POLICY = """You are a procurement policy advisor. Given the inventory record, the
selected vendor choice and the requested quantity, advise on a draft purchase requisition:
- Quantity must meet or exceed the vendor MOQ and must not cause more than 90 days of
  cover (qty / daily_demand <= 90).
- Prefer vendors with lower price; within 3% price, prefer faster lead time.
Respond with JSON only: {"approve": true, "reason": "...", "recommended_qty": 0}
"""


def _rule_checks(inv: dict, choice: dict, qty: int) -> dict:
    daily = float(inv["daily_demand"]) or 0.0
    cover_days = round(qty / daily, 1) if daily > 0 else 999.0
    moq = int(choice["moq"])
    return {
        "moq": {"required": moq, "requested": qty, "ok": qty >= moq},
        "cover_days": {"value": cover_days, "max": COVER_DAYS_MAX, "ok": cover_days <= COVER_DAYS_MAX},
        "price_sanity": {
            "deviation_pct": choice.get("deviation_pct"),
            "max_pct": 15.0,
            "ok": bool(choice.get("price_ok")),
        },
    }


def _rule_verdict(inv: dict, choice: dict, qty: int, checks: dict) -> dict:
    failed = [name for name, check in checks.items() if not check["ok"]]
    if failed:
        reasons = {
            "moq": f"quantity {qty} is below vendor MOQ {choice['moq']}",
            "cover_days": (
                f"cover of {checks['cover_days']['value']} days exceeds the {COVER_DAYS_MAX}-day cap"
            ),
            "price_sanity": (
                "live price deviates "
                f"{checks['price_sanity']['deviation_pct']}% — beyond the ±15% sanity band"
            ),
        }
        reason = "Blocked by policy: " + "; ".join(reasons[name] for name in failed)
    else:
        reason = "All policy checks passed: MOQ met, cover within 90 days, price within ±15%."
    return {"approve": not failed, "reason": reason, "recommended_qty": qty,
            "checks": checks, "engine": "policy-rules"}


def _ollama_advice(inv: dict, choice: dict, qty: int, checks: dict) -> dict | None:
    """Ask the local model for a narrative + quantity refinement. Any failure -> None."""
    vendor_view = {k: choice[k] for k in ("name", "live_price", "moq", "lead_time_days")}
    prompt = (
        f"{PROC_POLICY}\nInventory={inv}\nVendorChoice={vendor_view}\n"
        f"RequestedQty={qty}\nCoverDays={checks['cover_days']['value']}"
    )
    try:
        res = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
                  "options": {"temperature": 0, "num_predict": 200}},
            timeout=60,
        )
        res.raise_for_status()
        txt = re.sub(r"```(json)?|```", "", res.json().get("response", "")).strip()
        out = json.loads(txt[txt.index("{"): txt.rindex("}") + 1])
        moq = int(choice["moq"])
        cover_cap = max(int(float(inv["daily_demand"]) * COVER_DAYS_MAX), moq)
        recommended = min(max(int(out.get("recommended_qty", qty)), moq), cover_cap)
        return {"reason": str(out.get("reason", "")).strip()[:280] or "Advisor approved.",
                "recommended_qty": recommended, "engine": f"ollama:{OLLAMA_MODEL}"}
    except Exception:
        return None


def advise(inv: dict, choice: dict, qty: int) -> dict:
    """Deterministic policy checks are the gate; the local LLM only advises.

    Rules decide approve/reject so the agent stays safe with or without a model;
    when rules pass, Ollama (if reachable) refines the reason and quantity."""
    checks = _rule_checks(inv, choice, qty)
    verdict = _rule_verdict(inv, choice, qty, checks)
    if not verdict["approve"]:
        return verdict
    advice = _ollama_advice(inv, choice, qty, checks)
    if advice:
        verdict.update(reason=advice["reason"], recommended_qty=advice["recommended_qty"],
                       engine=advice["engine"])
    return verdict
