from datetime import datetime, timezone

from sqlalchemy import text

from fin_db import engine


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _div(num, den):
    if not num or not den:
        return None
    return round(num / den, 3)


def _pct(num, den):
    if num is None or not den:
        return None
    return round(num / den * 100, 2)


def _growth(curr, prev):
    if curr is None or prev is None or prev == 0:
        return None
    return round((curr - prev) / abs(prev) * 100, 2)


# Ratio suite scored against sector benchmarks (weights sum to 100).
# unit: "x" (times), "%" (percent) or "$M" (millions USD).
SCORED_RATIOS = [
    {"key": "current_ratio", "label": "Current ratio", "weight": 12, "unit": "x"},
    {"key": "quick_ratio", "label": "Quick ratio", "weight": 8, "unit": "x"},
    {"key": "debt_to_equity", "label": "Debt-to-equity", "weight": 14, "unit": "x"},
    {"key": "interest_coverage", "label": "Interest coverage", "weight": 16, "unit": "x"},
    {"key": "gross_margin", "label": "Gross margin", "weight": 8, "unit": "%"},
    {"key": "operating_margin", "label": "Operating margin", "weight": 12, "unit": "%"},
    {"key": "net_margin", "label": "Net margin", "weight": 12, "unit": "%"},
    {"key": "revenue_growth", "label": "Revenue growth", "weight": 8, "unit": "%"},
    {"key": "free_cash_flow", "label": "Free cash flow", "weight": 10, "unit": "$M"},
]

WATCH_SHARE = 0.45  # points granted while a ratio sits in the watch band

GRADE_BANDS = [(90, "A"), (80, "B"), (70, "C"), (60, "D")]
GRADE_VERDICT = {"A": "Strong", "B": "Strong", "C": "Healthy", "D": "Watch", "F": "Distressed"}


def compute_ratios(rows: list[dict]) -> list[dict]:
    """Deterministic ratio suite per fiscal year. Returns one dict per year, oldest first."""
    out = []
    prev = None
    for r in rows:
        rev = r["revenue"] or 0
        cogs = r["cogs"] or 0
        opex = r["opex"] or 0
        gp = rev - cogs
        opinc = rev - cogs - opex
        out.append({
            "fiscal_year": r["year"],
            "revenue": rev,
            "gross_profit": gp,
            "operating_income": opinc,
            "net_income": r["net_income"],
            "current_ratio": _div(r["current_assets"], r["current_liabilities"]),
            "quick_ratio": _div((r["current_assets"] or 0) - (r["inventory"] or 0),
                                r["current_liabilities"]),
            "debt_to_equity": _div(r["total_debt"], r["equity"]),
            "interest_coverage": _div(opinc, r["interest"]),
            "gross_margin": _pct(gp, rev),
            "operating_margin": _pct(opinc, rev),
            "net_margin": _pct(r["net_income"], rev),
            "roe": _pct(r["net_income"], r["equity"]),
            "roa": _pct(r["net_income"], r["total_assets"]),
            "ocf_margin": _pct(r["operating_cash_flow"], rev),
            "free_cash_flow": round((r["operating_cash_flow"] or 0) - (r["capex"] or 0), 1),
            "revenue_growth": _growth(rev, prev["revenue"]) if prev else None,
            "net_income_growth": _growth(r["net_income"], prev["net_income"]) if prev else None,
        })
        prev = r
    return out


def _ratio_status(key: str, value, bench: dict) -> str:
    if key == "free_cash_flow":
        if value is None:
            return "concern"
        if value > 0:
            return "healthy"
        if value == 0:
            return "watch"
        return "concern"
    if value is None:
        return "concern"
    if bench["lower_better"]:
        if value <= bench["healthy"]:
            return "healthy"
        if value <= bench["watch"]:
            return "watch"
        return "concern"
    if value >= bench["healthy"]:
        return "healthy"
    if value >= bench["watch"]:
        return "watch"
    return "concern"


def score_health(latest: dict, benchmarks: dict) -> dict:
    """Health score 0-100: each scored ratio earns full weight in the healthy band,
    45% of it in the watch band, zero when off-band. Grade and verdict follow the score."""
    contributions = []
    score = 0.0
    for meta in SCORED_RATIOS:
        key = meta["key"]
        bench = benchmarks[key]
        value = latest.get(key)
        status = _ratio_status(key, value, bench)
        points = round(meta["weight"] * (1.0 if status == "healthy"
                                         else WATCH_SHARE if status == "watch" else 0.0), 1)
        score += points
        contributions.append({
            "ratio": key, "label": meta["label"], "unit": meta["unit"],
            "value": value, "status": status,
            "healthy": bench["healthy"], "watch": bench["watch"],
            "median": bench["median"], "lower_better": bench["lower_better"],
            "absolute": bench.get("absolute", False),
            "weight": meta["weight"], "points": points,
        })
    score = round(score, 1)
    grade = next((g for floor, g in GRADE_BANDS if score >= floor), "F")
    return {"score": score, "grade": grade, "verdict": GRADE_VERDICT[grade],
            "contributions": contributions}


def detect_red_flags(rows: list[dict], ratios: list[dict]) -> list[dict]:
    """Deterministic flag engine — the authority on risk flags, independent of the LLM."""
    latest, prev1, prev2 = ratios[-1], (ratios[-2] if len(ratios) > 1 else None), \
        (ratios[-3] if len(ratios) > 2 else None)
    flags = []

    cr = latest["current_ratio"]
    if cr is not None and cr < 1.0:
        flags.append({"code": "liquidity_strain", "label": "Liquidity strain",
                      "detail": f"Current ratio {cr} is below 1.0 — short-term obligations "
                                f"exceed liquid assets."})

    ic = latest["interest_coverage"]
    if ic is None or ic < 2.0:
        seen = f"{ic}x" if ic is not None else "negative operating income"
        flags.append({"code": "debt_service_risk", "label": "Debt-service risk",
                      "detail": f"Interest coverage {seen} is below the 2.0x floor — "
                                f"earnings barely (or do not) cover interest."})

    fcf = latest["free_cash_flow"]
    if fcf is not None and fcf < 0:
        flags.append({"code": "cash_burn", "label": "Cash burn",
                      "detail": f"Free cash flow is negative ({fcf}M) in the latest fiscal year."})
        if prev1 and prev1["free_cash_flow"] is not None and prev1["free_cash_flow"] < 0:
            flags.append({"code": "persistent_cash_burn", "label": "Persistent cash burn",
                          "detail": f"FCF negative two consecutive years ({prev1['free_cash_flow']}M, "
                                    f"{fcf}M) — the company is consuming its reserves."})

    if prev2 and None not in (latest["net_margin"], prev1["net_margin"], prev2["net_margin"]) \
            and latest["net_margin"] < prev1["net_margin"] < prev2["net_margin"]:
        flags.append({"code": "margin_erosion", "label": "Margin erosion",
                      "detail": f"Net margin declined two years running "
                                f"({prev2['net_margin']}% -> {prev1['net_margin']}% -> "
                                f"{latest['net_margin']}%)."})

    rg = latest["revenue_growth"]
    if rg is not None and rg < 0:
        flags.append({"code": "revenue_decline", "label": "Top-line contraction",
                      "detail": f"Revenue fell {abs(rg)}% year over year."})

    de = latest["debt_to_equity"]
    if de is not None and de > 2.0:
        flags.append({"code": "high_leverage", "label": "High leverage",
                      "detail": f"Debt-to-equity {de}x is above the 2.0x ceiling."})

    last_row = rows[-1]
    if (last_row["operating_cash_flow"] or 0) < 0 and (last_row["net_income"] or 0) > 0:
        flags.append({"code": "earnings_quality", "label": "Earnings-quality flag",
                      "detail": "Reported net income is positive while operating cash flow "
                                "is negative — profits are not converting to cash."})
    return flags


def get_company(ticker: str) -> dict:
    with engine.begin() as con:
        row = con.execute(text("SELECT * FROM company WHERE ticker=:t"), {"t": ticker}).mappings().first()
        return dict(row) if row else {}


def get_statements(ticker: str) -> list[dict]:
    with engine.begin() as con:
        rows = con.execute(
            text("SELECT * FROM financials WHERE ticker=:t ORDER BY year ASC"), {"t": ticker}
        ).mappings().all()
        return [dict(r) for r in rows]


def list_companies() -> list[dict]:
    """Company roster enriched with the latest brief (if any) for dashboards."""
    with engine.begin() as con:
        comps = [dict(r) for r in con.execute(text("SELECT * FROM company ORDER BY ticker")).mappings()]
        for c in comps:
            stmts = get_statements(c["ticker"])
            ratios = compute_ratios(stmts)
            latest_stmt = stmts[-1] if stmts else {}
            c["latest_revenue"] = latest_stmt.get("revenue")
            c["revenue_history"] = [r["revenue"] for r in ratios]
            c["latest_ratios"] = ratios[-1] if ratios else {}
            brief = con.execute(
                text("SELECT * FROM brief WHERE ticker=:t ORDER BY id DESC LIMIT 1"),
                {"t": c["ticker"]},
            ).mappings().first()
            c["last_brief"] = dict(brief) if brief else None
        return comps


def draft_brief(ticker: str, fiscal_year: int, score: float, grade: str, verdict: str,
                flags_count: int, narrative: str, key_risks: str, prepared_by: str) -> dict:
    """Create an analyst brief in 'draft' status — never publishes it."""
    with engine.begin() as con:
        brief_id = con.execute(
            text(
                """INSERT INTO brief(ticker, fiscal_year, score, grade, verdict, flags_count,
                                     status, prepared_by, reviewed_by, narrative, key_risks,
                                     created_at, published_at)
                   VALUES(:t,:fy,:sc,:g,:v,:fc,'draft',:pb,NULL,:n,:kr,:ts,NULL)
                   RETURNING id"""
            ),
            {"t": ticker, "fy": fiscal_year, "sc": score, "g": grade, "v": verdict,
             "fc": flags_count, "pb": prepared_by, "n": narrative, "kr": key_risks, "ts": _now()},
        ).scalar()
    return {
        "id": brief_id,
        "ticker": ticker,
        "fiscal_year": fiscal_year,
        "score": score,
        "grade": grade,
        "verdict": verdict,
        "flags_count": flags_count,
        "status": "draft",
        "prepared_by": prepared_by,
    }


def publish_brief(brief_id: int, reviewer: str) -> dict:
    """Human sign-off gate: preparer and reviewer must differ (separation of duties)."""
    with engine.begin() as con:
        row = con.execute(text("SELECT * FROM brief WHERE id=:i"), {"i": brief_id}).mappings().first()
        if not row:
            return {"ok": False, "error": f"Brief #{brief_id} not found"}
        brief = dict(row)
        if brief["status"] != "draft":
            return {"ok": False, "error": f"Brief #{brief_id} is already {brief['status']}"}
        if reviewer and reviewer.lower() == (brief["prepared_by"] or "").lower():
            return {"ok": False,
                    "error": "Separation of duties: the preparer cannot sign off their own brief"}
        con.execute(
            text("UPDATE brief SET status='published', reviewed_by=:r, published_at=:ts WHERE id=:i"),
            {"r": reviewer, "ts": _now(), "i": brief_id},
        )
    return {
        "ok": True,
        "id": brief_id,
        "ticker": brief["ticker"],
        "status": "published",
        "reviewed_by": reviewer,
        "score": brief["score"],
        "grade": brief["grade"],
    }


def list_open_briefs() -> list[dict]:
    with engine.begin() as con:
        rows = con.execute(text("SELECT * FROM brief WHERE status='draft' ORDER BY id DESC")).mappings().all()
        return [dict(r) for r in rows]


def list_recent_briefs(limit: int = 12) -> list[dict]:
    with engine.begin() as con:
        rows = con.execute(text("SELECT * FROM brief ORDER BY id DESC LIMIT :n"), {"n": limit}).mappings().all()
        return [dict(r) for r in rows]
