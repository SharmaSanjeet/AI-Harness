from fin import (compute_ratios, detect_red_flags, draft_brief, get_company,
                 get_statements, score_health)
from analyst_llm import advise
from market_api import data_quality, get_sector_benchmarks


def analyze_company(ticker: str, prepared_by: str) -> dict:
    """Full flow: profile -> statements -> data-quality gate -> ratio suite ->
    sector benchmarks -> health score -> red flags -> LLM narrative -> draft brief.
    Every step is returned so UIs can render a trace."""
    steps = []

    company = get_company(ticker)
    steps.append({"tool": "get_company_profile", "label": "Company profile",
                  "args": {"ticker": ticker}, "result": company or {"found": False}})
    if not company:
        return {"ok": False,
                "error": f"Ticker '{ticker}' not found — pick a listed company or reset the demo data.",
                "steps": steps}

    statements = get_statements(ticker)
    if not statements:
        return {"ok": False,
                "error": f"No financial statements on file for '{ticker}'.",
                "steps": steps}
    steps.append({"tool": "get_financial_statements", "label": "Financial statements",
                  "args": {"years": len(statements)},
                  "result": [{"fiscal_year": s["year"], "revenue": s["revenue"],
                              "operating_income": s["revenue"] - s["cogs"] - s["opex"],
                              "net_income": s["net_income"]} for s in statements]})

    dq = data_quality(statements)
    steps.append({"tool": "data_quality", "label": "Data-quality gate",
                  "args": {"tolerance_pct": dq["tolerance_pct"]}, "result": dq})
    if not dq["ok"]:
        return {"ok": True, "ticker": ticker,
                "company": {"name": company["name"], "sector": company["sector"]},
                "error": None,
                "recommendation": "Analysis blocked — balance-sheet data failed the integrity check.",
                "data_quality": dq, "score": None, "grade": None, "verdict": None,
                "red_flags": [], "narrative": None, "brief": None,
                "review": {"status": "blocked", "reason": "Statement data failed the "
                           "assets = liabilities + equity integrity check."},
                "steps": steps}

    ratios = compute_ratios(statements)
    latest = ratios[-1]
    latest_view = {k: v for k, v in latest.items()
                   if k not in ("gross_profit", "operating_income", "net_income")}
    steps.append({"tool": "compute_ratios", "label": "Ratio suite",
                  "args": {"fiscal_year": latest["fiscal_year"]}, "result": latest_view})

    benchmarks = get_sector_benchmarks(company["sector"])
    steps.append({"tool": "benchmark_sector", "label": "Sector benchmarks",
                  "args": {"sector": company["sector"]},
                  "result": {k: {kk: band[kk] for kk in ("healthy", "watch", "median",
                                                         "lower_better")}
                             for k, band in benchmarks.items()
                             if not band.get("absolute")}})

    score = score_health(latest, benchmarks)
    steps.append({"tool": "score_health", "label": "Health score",
                  "args": {"weights_sum": sum(c["weight"] for c in score["contributions"])},
                  "result": {"score": score["score"], "grade": score["grade"],
                             "verdict": score["verdict"],
                             "off_band": sum(1 for c in score["contributions"]
                                             if c["status"] != "healthy")}})

    flags = detect_red_flags(statements, ratios)
    steps.append({"tool": "detect_red_flags", "label": "Red-flag engine",
                  "args": {"rules": "liquidity, debt service, cash burn, margin erosion, "
                                    "leverage, earnings quality"},
                  "result": flags})

    advice = advise(company, latest["fiscal_year"], score, flags, ratios)
    steps.append({"tool": "advise", "label": "Analyst advisor",
                  "args": {"engine": advice["engine"]},
                  "result": {"narrative": advice["narrative"],
                             "key_risks": advice["key_risks"],
                             "engine": advice["engine"]}})

    brief = draft_brief(ticker, latest["fiscal_year"], score["score"], score["grade"],
                        score["verdict"], len(flags), advice["narrative"],
                        advice["key_risks"], prepared_by)
    steps.append({"tool": "draft_brief", "label": "Analyst brief drafted",
                  "args": {"ticker": ticker, "prepared_by": prepared_by},
                  "result": brief})

    return {
        "ok": True, "ticker": ticker,
        "company": {"name": company["name"], "sector": company["sector"],
                    "description": company["description"]},
        "fiscal_year": latest["fiscal_year"],
        "score": score["score"], "grade": score["grade"], "verdict": score["verdict"],
        "contributions": score["contributions"],
        "benchmarks": benchmarks,
        "red_flags": flags,
        "narrative": advice["narrative"],
        "key_risks": advice["key_risks"],
        "advisor_engine": advice["engine"],
        "brief": brief,
        "review": {"status": "pending_human_signoff",
                   "note": "Brief is a draft — a human analyst must sign off via "
                           "POST /briefs/{id}/publish. The agent never publishes analysis."},
        "steps": steps,
    }
