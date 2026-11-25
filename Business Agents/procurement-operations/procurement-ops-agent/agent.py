from ops import draft_pr, get_inventory, need_reorder
from policy_llm import advise
from vendors_api import choose_vendor, fetch_live_quotes

TARGET_COVER_DAYS = 30


def assess_and_draft(sku: str, requested_by: str) -> dict:
    """Full flow: inventory -> ROP math -> live quotes -> vendor selection ->
    policy gate -> pending PR. Every step is returned so UIs can render a trace."""
    steps = []

    inv = get_inventory(sku)
    steps.append({"tool": "get_inventory", "label": "Inventory check",
                  "args": {"sku": sku}, "result": inv or {"found": False}})
    if not inv:
        return {"ok": False,
                "error": f"SKU '{sku}' not found — pick a listed SKU or reset the demo data.",
                "steps": steps}

    need = need_reorder(inv)
    steps.append({"tool": "need_reorder", "label": "Reorder-point math",
                  "args": {"daily_demand": inv["daily_demand"],
                           "lead_time_days": inv["lead_time_days"],
                           "safety_stock": inv["safety_stock"]},
                  "result": need})

    quotes = fetch_live_quotes(sku)
    steps.append({"tool": "fetch_live_quotes", "label": "Live vendor quotes",
                  "args": {"sku": sku, "vendors": len(quotes)},
                  "result": [{k: q[k] for k in ("name", "live_price", "deviation_pct",
                                                "moq", "lead_time_days", "price_ok")}
                             for q in quotes]})

    if not need["needs_reorder"]:
        return {
            "ok": True, "sku": sku, "needs_reorder": False,
            "reorder_point": need["reorder_point"], "position": need["position"],
            "recommendation": (f"Position {need['position']} is above the reorder point "
                               f"{need['reorder_point']} — no replenishment needed."),
            "selected_vendor": None, "policy": None, "pr": None,
            "approval": {"status": "not_required", "reason": "Stock position is healthy."},
            "steps": steps,
        }

    target_qty = max(int(inv["daily_demand"] * TARGET_COVER_DAYS) - inv["on_hand"] - inv["on_order"], 1)
    choice = choose_vendor(quotes, target_qty)
    steps.append({"tool": "choose_vendor", "label": "Vendor selection (MOQ + price sanity)",
                  "args": {"target_qty": target_qty},
                  "result": ({k: choice[k] for k in ("name", "live_price", "moq",
                                                     "lead_time_days", "qty", "selection")}
                             if choice else {"price_ok_vendors": 0})})
    if choice is None:
        return {
            "ok": True, "sku": sku, "needs_reorder": True,
            "reorder_point": need["reorder_point"], "position": need["position"],
            "recommendation": "Every live quote failed the ±15% price-sanity check — PR blocked.",
            "selected_vendor": None,
            "policy": {"approve": False, "reason": "No price-sane vendor available.",
                       "checks": {}, "engine": "policy-rules"},
            "pr": None,
            "approval": {"status": "blocked", "reason": "Price-sanity guardrail rejected all quotes."},
            "steps": steps,
        }

    qty = int(choice["qty"])
    advice = advise(inv, choice, qty)
    steps.append({"tool": "advise", "label": "Policy advisor",
                  "args": {"vendor": choice["name"], "qty": qty}, "result": advice})

    if not advice["approve"]:
        return {
            "ok": True, "sku": sku, "needs_reorder": True,
            "reorder_point": need["reorder_point"], "position": need["position"],
            "recommendation": f"PR blocked by policy — {advice['reason']}",
            "selected_vendor": {"name": choice["name"], "unit_price": choice["live_price"],
                                "moq": choice["moq"], "lead_time_days": choice["lead_time_days"],
                                "qty": qty, "moq_adjusted": choice["moq_adjusted"],
                                "selection": choice["selection"]},
            "policy": advice, "pr": None,
            "approval": {"status": "blocked", "reason": advice["reason"]},
            "steps": steps,
        }

    pr = draft_pr(sku, choice["name"], qty, choice["live_price"], requested_by)
    steps.append({"tool": "draft_pr", "label": "Purchase requisition drafted",
                  "args": {"sku": sku, "vendor": choice["name"], "qty": qty,
                           "requested_by": requested_by},
                  "result": pr})

    return {
        "ok": True, "sku": sku, "needs_reorder": True,
        "reorder_point": need["reorder_point"], "position": need["position"],
        "target_qty": target_qty,
        "selected_vendor": {"name": choice["name"], "unit_price": choice["live_price"],
                            "moq": choice["moq"], "lead_time_days": choice["lead_time_days"],
                            "qty": qty, "moq_adjusted": choice["moq_adjusted"],
                            "selection": choice["selection"]},
        "policy": advice,
        "pr": pr,
        "approval": {"status": "pending_human_signoff", "reason": advice["reason"],
                     "note": "PR is pending — a human must approve via POST /approve/{pr_id}. "
                             "The agent never places orders."},
        "steps": steps,
    }
