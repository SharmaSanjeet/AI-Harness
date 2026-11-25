from datetime import datetime, timezone

from sqlalchemy import text

from ops_db import engine


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def calc_reorder_point(daily_demand: float, lead: int, safety: int) -> int:
    """ROP = (avg daily demand x lead time) + safety stock."""
    return int(round(daily_demand * lead + safety))


def need_reorder(inv: dict) -> dict:
    if not inv:
        return {"ok": False, "reason": "SKU not found"}
    rop = calc_reorder_point(inv["daily_demand"], inv["lead_time_days"], inv["safety_stock"])
    position = inv["on_hand"] + inv["on_order"]
    return {"ok": True, "reorder_point": rop, "position": position, "needs_reorder": position <= rop}


def inventory_status(inv: dict) -> dict:
    """Enrich an inventory row with ROP math and a status bucket for dashboards."""
    need = need_reorder(inv)
    if not need.get("ok"):
        return inv
    rop, position = need["reorder_point"], need["position"]
    if position <= rop:
        status = "reorder"
    elif position <= rop * 1.25:
        status = "watch"
    else:
        status = "ok"
    return {
        **inv,
        "reorder_point": rop,
        "position": position,
        "needs_reorder": need["needs_reorder"],
        "status": status,
    }


def get_inventory(sku: str) -> dict:
    with engine.begin() as con:
        row = con.execute(text("SELECT * FROM inventory WHERE sku=:s"), {"s": sku}).mappings().first()
        return dict(row) if row else {}


def list_inventory() -> list[dict]:
    with engine.begin() as con:
        rows = con.execute(text("SELECT * FROM inventory ORDER BY sku")).mappings().all()
        return [inventory_status(dict(r)) for r in rows]


def get_vendors(sku: str) -> list[dict]:
    with engine.begin() as con:
        rows = con.execute(
            text("SELECT * FROM vendors WHERE sku=:s ORDER BY price_usd ASC"), {"s": sku}
        ).mappings().all()
        return [dict(r) for r in rows]


def draft_pr(sku: str, vendor: str, qty: int, price: float, requested_by: str) -> dict:
    """Create a purchase requisition in 'pending' status — never places an order."""
    with engine.begin() as con:
        con.execute(
            text(
                """INSERT INTO pr(sku,qty,vendor,price_usd,status,requested_by,approved_by,created_at)
                   VALUES(:sku,:qty,:v,:p,'pending',:rb,NULL,:ts)"""
            ),
            {"sku": sku, "qty": qty, "v": vendor, "p": price, "rb": requested_by, "ts": _now()},
        )
        pr_id = con.execute(text("SELECT last_insert_rowid()")).scalar()
    return {
        "id": pr_id,
        "status": "pending",
        "sku": sku,
        "vendor": vendor,
        "qty": qty,
        "unit_price": round(price, 2),
        "line_total": round(qty * price, 2),
        "requested_by": requested_by,
    }


def approve_pr(pr_id: int, approver: str) -> dict:
    """Human sign-off gate: requester and approver must differ (separation of duties).

    On approval the PR's quantity moves into inventory on_order, closing the loop."""
    with engine.begin() as con:
        row = con.execute(text("SELECT * FROM pr WHERE id=:i"), {"i": pr_id}).mappings().first()
        if not row:
            return {"ok": False, "error": f"PR #{pr_id} not found"}
        pr = dict(row)
        if pr["status"] != "pending":
            return {"ok": False, "error": f"PR #{pr_id} is already {pr['status']}"}
        if approver and approver.lower() == (pr["requested_by"] or "").lower():
            return {"ok": False, "error": "Separation of duties: the requester cannot approve their own PR"}
        con.execute(
            text("UPDATE pr SET status='approved', approved_by=:a WHERE id=:i"),
            {"a": approver, "i": pr_id},
        )
        con.execute(
            text("UPDATE inventory SET on_order = on_order + :q WHERE sku = :s"),
            {"q": pr["qty"], "s": pr["sku"]},
        )
    return {
        "ok": True,
        "id": pr_id,
        "status": "approved",
        "approved_by": approver,
        "sku": pr["sku"],
        "qty": pr["qty"],
        "on_order_added": pr["qty"],
    }


def list_open_pr() -> list[dict]:
    with engine.begin() as con:
        rows = con.execute(text("SELECT * FROM pr WHERE status='pending' ORDER BY id DESC")).mappings().all()
        return [dict(r) for r in rows]


def list_recent_pr(limit: int = 12) -> list[dict]:
    with engine.begin() as con:
        rows = con.execute(text("SELECT * FROM pr ORDER BY id DESC LIMIT :n"), {"n": limit}).mappings().all()
        return [dict(r) for r in rows]
