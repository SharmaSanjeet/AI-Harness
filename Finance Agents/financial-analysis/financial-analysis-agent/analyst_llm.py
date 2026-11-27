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

FIN_ANALYST = """You are a senior financial analyst writing the narrative section of an
internal analyst brief. You are given the company, its computed ratios for the latest
fiscal year, sector benchmark bands, the health score/grade/verdict assigned by a
deterministic engine, and the red flags that engine raised.
- Be factual: only reference the numbers provided; never invent data.
- No buy/sell recommendation — this is an internal financial-health assessment.
- Narrative: 3-5 sentences covering the trend story, strengths and what to monitor.
- key_risks: one or two sentences on the biggest risks, or "None material" if clean.
Respond with JSON only: {"narrative": "...", "key_risks": "..."}
"""


def _fmt(value, unit) -> str:
    if value is None:
        return "n/a"
    if unit == "%":
        return f"{value}%"
    if unit == "$M":
        return f"{value}M"
    return f"{value}x"


def _band_word(contrib) -> str:
    b = contrib
    if b["lower_better"]:
        return f"healthy <= {b['healthy']}, watch <= {b['watch']}"
    if b.get("absolute"):
        return "healthy > 0, negative = off-band"
    return f"healthy >= {b['healthy']}, watch >= {b['watch']}"


def _rule_narrative(company: dict, fiscal_year: int, score: dict, flags: list[dict]) -> dict:
    """Deterministic fallback narrative — built only from computed facts."""
    name, sector = company["name"], company["sector"]
    scored = score["contributions"]
    strong = [c for c in scored if c["status"] == "healthy"]
    watch = [c for c in scored if c["status"] == "watch"]
    weak = [c for c in scored if c["status"] == "concern"]

    parts = [
        f"{name} ({sector}) scores {score['score']}/100 (grade {score['grade']}) for "
        f"FY{fiscal_year} — a {score['verdict'].lower()} financial profile."
    ]
    if strong:
        parts.append("Inside the sector healthy band: " +
                     ", ".join(f"{c['label']} {_fmt(c['value'], c['unit'])}" for c in strong) + ".")
    if watch:
        parts.append("Below the healthy band but watchable: " +
                     ", ".join(f"{c['label']} {_fmt(c['value'], c['unit'])}" for c in watch) + ".")
    if weak:
        parts.append("Off-band: " +
                     ", ".join(f"{c['label']} {_fmt(c['value'], c['unit'])}" for c in weak) + ".")

    if flags:
        risks = " ".join(f"{f['label']}: {f['detail']}" for f in flags)
        parts.append(f"The rule engine raised {len(flags)} red flag(s): "
                     + ", ".join(f["label"] for f in flags) + ".")
    else:
        risks = "None material — no red flags raised by the rule engine."
        parts.append("The rule engine raised no red flags.")
    return {"narrative": " ".join(parts), "key_risks": risks, "engine": "rule-narrative"}


def _ollama_narrative(view: dict) -> dict | None:
    """Ask the local model for the analyst narrative. Any failure -> None."""
    prompt = f"{FIN_ANALYST}\nCompanyData={json.dumps(view, default=str)}"
    try:
        res = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
                  "options": {"temperature": 0.4, "num_predict": 320}},
            timeout=90,
        )
        res.raise_for_status()
        txt = re.sub(r"```(json)?|```", "", res.json().get("response", "")).strip()
        out = json.loads(txt[txt.index("{"): txt.rindex("}") + 1])
        narrative = str(out.get("narrative", "")).strip()
        key_risks = str(out.get("key_risks", "")).strip()
        if not narrative:
            return None
        return {"narrative": narrative[:900],
                "key_risks": (key_risks or "None material.")[:400],
                "engine": f"ollama:{OLLAMA_MODEL}"}
    except Exception:
        return None


def advise(company: dict, fiscal_year: int, score: dict, flags: list[dict],
           ratio_history: list[dict]) -> dict:
    """Deterministic engine decides score, grade, verdict and flags; the local LLM
    only writes the narrative. Falls back to a rule-built narrative without a model."""
    fallback = _rule_narrative(company, fiscal_year, score, flags)

    scored = score["contributions"]
    trend_keys = ("revenue", "net_margin", "current_ratio", "debt_to_equity", "free_cash_flow")
    trend = {k: [r.get(k) for r in ratio_history] for k in trend_keys}
    view = {
        "company": company["name"], "sector": company["sector"], "fiscal_year": fiscal_year,
        "score": score["score"], "grade": score["grade"], "verdict": score["verdict"],
        "ratios": {c["label"]: _fmt(c["value"], c["unit"]) for c in scored},
        "sector_bands": {c["label"]: _band_word(c) for c in scored},
        "three_year_trend": trend,
        "red_flags": [{"label": f["label"], "detail": f["detail"]} for f in flags],
    }
    advice = _ollama_narrative(view)
    if advice:
        fallback.update(narrative=advice["narrative"],
                        key_risks=advice["key_risks"], engine=advice["engine"])
    return fallback
