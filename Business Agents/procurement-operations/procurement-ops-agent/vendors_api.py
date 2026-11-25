import random

from ops import get_vendors

# Guardrail: live quotes deviating more than ±15% from the catalog price are rejected.
PRICE_SANITY_PCT = 15.0


def fetch_live_quotes(sku: str) -> list[dict]:
    """Mock vendor portal: catalog prices with a small live jitter plus a sanity flag.

    In production this is the outbound call to vendor price APIs; the selection
    policy below stays unchanged."""
    quotes = []
    for v in get_vendors(sku):
        live_price = round(v["price_usd"] * (1 + random.uniform(-0.02, 0.02)), 2)
        deviation_pct = round((live_price / v["price_usd"] - 1) * 100, 2)
        quotes.append(
            {
                **v,
                "live_price": live_price,
                "deviation_pct": deviation_pct,
                "price_ok": abs(deviation_pct) <= PRICE_SANITY_PCT,
            }
        )
    return quotes


def choose_vendor(quotes: list[dict], qty: int) -> dict | None:
    """Lowest live price meeting MOQ, tie-broken by lead time, price-sanity enforced.

    Below every vendor's MOQ -> cheapest vendor with the smallest MOQ and the
    quantity raised to that MOQ (policy keeps the PR legal, the human approves it).
    Returns None when every quote fails the price-sanity check."""
    sane = [q for q in quotes if q["price_ok"]]
    if not sane:
        return None
    candidates = [q for q in sane if qty >= q["moq"]]
    if candidates:
        best = sorted(candidates, key=lambda q: (q["live_price"], q["lead_time_days"]))[0]
        return {**best, "qty": qty, "moq_adjusted": False,
                "selection": "lowest live price meeting MOQ; tie-break lead time"}
    fallback = min(sane, key=lambda q: (q["moq"], q["live_price"]))
    return {**fallback, "qty": max(qty, fallback["moq"]), "moq_adjusted": True,
            "selection": "requested qty below MOQ — quantity raised to vendor MOQ"}
