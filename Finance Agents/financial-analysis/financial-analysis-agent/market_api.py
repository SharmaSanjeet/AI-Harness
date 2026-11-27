# Mock market-data provider: sector benchmark bands for the scored ratio suite.
# In production this is the outbound call to a benchmarks/fundamentals API; the
# scoring and flag engines stay unchanged.

# Each entry: healthy band edge, watch band edge and a sector median for display.
# debt_to_equity is lower-is-better; every other band is higher-is-better.
SECTOR_BENCHMARKS = {
    "Technology": {
        "current_ratio": {"healthy": 2.0, "watch": 1.2, "median": 1.8},
        "quick_ratio": {"healthy": 1.5, "watch": 0.8, "median": 1.3},
        "debt_to_equity": {"healthy": 0.6, "watch": 1.2, "median": 0.9},
        "interest_coverage": {"healthy": 8, "watch": 4, "median": 6},
        "gross_margin": {"healthy": 55, "watch": 40, "median": 48},
        "operating_margin": {"healthy": 18, "watch": 8, "median": 12},
        "net_margin": {"healthy": 12, "watch": 5, "median": 8},
        "revenue_growth": {"healthy": 15, "watch": 5, "median": 10},
    },
    "Industrials": {
        "current_ratio": {"healthy": 1.8, "watch": 1.1, "median": 1.5},
        "quick_ratio": {"healthy": 1.0, "watch": 0.6, "median": 0.9},
        "debt_to_equity": {"healthy": 1.0, "watch": 1.8, "median": 1.4},
        "interest_coverage": {"healthy": 5, "watch": 2.5, "median": 3.5},
        "gross_margin": {"healthy": 32, "watch": 24, "median": 28},
        "operating_margin": {"healthy": 12, "watch": 6, "median": 9},
        "net_margin": {"healthy": 7, "watch": 3, "median": 5},
        "revenue_growth": {"healthy": 8, "watch": 2, "median": 5},
    },
    "Retail": {
        "current_ratio": {"healthy": 1.5, "watch": 1.0, "median": 1.3},
        "quick_ratio": {"healthy": 0.7, "watch": 0.4, "median": 0.6},
        "debt_to_equity": {"healthy": 1.2, "watch": 2.0, "median": 1.6},
        "interest_coverage": {"healthy": 5, "watch": 2.5, "median": 3.5},
        "gross_margin": {"healthy": 30, "watch": 22, "median": 26},
        "operating_margin": {"healthy": 8, "watch": 4, "median": 6},
        "net_margin": {"healthy": 4, "watch": 2, "median": 3},
        "revenue_growth": {"healthy": 6, "watch": 1, "median": 3.5},
    },
    "Transportation": {
        "current_ratio": {"healthy": 1.5, "watch": 1.0, "median": 1.2},
        "quick_ratio": {"healthy": 0.9, "watch": 0.5, "median": 0.7},
        "debt_to_equity": {"healthy": 1.5, "watch": 2.5, "median": 2.0},
        "interest_coverage": {"healthy": 4, "watch": 2, "median": 3},
        "gross_margin": {"healthy": 28, "watch": 20, "median": 24},
        "operating_margin": {"healthy": 10, "watch": 4, "median": 7},
        "net_margin": {"healthy": 5, "watch": 1, "median": 3},
        "revenue_growth": {"healthy": 6, "watch": 0, "median": 3},
    },
    "Healthcare": {
        "current_ratio": {"healthy": 2.2, "watch": 1.3, "median": 1.9},
        "quick_ratio": {"healthy": 1.6, "watch": 0.9, "median": 1.4},
        "debt_to_equity": {"healthy": 0.7, "watch": 1.4, "median": 1.0},
        "interest_coverage": {"healthy": 7, "watch": 3.5, "median": 5},
        "gross_margin": {"healthy": 60, "watch": 45, "median": 52},
        "operating_margin": {"healthy": 15, "watch": 7, "median": 11},
        "net_margin": {"healthy": 10, "watch": 4, "median": 7},
        "revenue_growth": {"healthy": 12, "watch": 4, "median": 8},
    },
}

LOWER_IS_BETTER = {"debt_to_equity"}
# Free cash flow is scored in absolute terms (positive / zero / negative), not banded.
FCF_PLACEHOLDER = {"healthy": 0, "watch": 0, "median": 0}

BALANCE_TOLERANCE_PCT = 2.0


def get_sector_benchmarks(sector: str) -> dict:
    """Benchmark bands for the scored ratios; unknown sectors fall back to Industrials."""
    base = SECTOR_BENCHMARKS.get(sector, SECTOR_BENCHMARKS["Industrials"])
    out = {}
    for key, band in base.items():
        out[key] = {
            "healthy": band["healthy"],
            "watch": band["watch"],
            "median": band["median"],
            "lower_better": key in LOWER_IS_BETTER,
        }
    out["free_cash_flow"] = {**FCF_PLACEHOLDER, "lower_better": False, "absolute": True}
    return out


def data_quality(rows: list[dict]) -> dict:
    """Balance-sheet integrity check: assets must equal liabilities + equity
    within tolerance. Severe inconsistencies get flagged before any scoring."""
    issues = []
    for r in rows:
        assets = r.get("total_assets") or 0
        rhs = (r.get("total_liabilities") or 0) + (r.get("equity") or 0)
        if assets and abs(assets - rhs) / assets > BALANCE_TOLERANCE_PCT / 100:
            issues.append(f"FY{r['year']}: assets {assets}M != liabilities + equity {rhs}M")
    return {
        "ok": not issues,
        "checked_years": len(rows),
        "tolerance_pct": BALANCE_TOLERANCE_PCT,
        "issues": issues,
    }
