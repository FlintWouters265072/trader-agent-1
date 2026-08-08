from __future__ import annotations


def clamp_order_value(requested_usd: float, max_order_value_usd: float) -> float:
    return max(0.0, min(requested_usd, max_order_value_usd))


def total_exposure_value(position_summaries: list[dict], symbol: str) -> float:
    symbol = symbol.strip().upper()
    return sum(
        abs(p.get("amount") or 0) * (p.get("current_price") or p.get("open_price") or 0)
        for p in position_summaries
        if (p.get("symbol") or "").strip().upper() == symbol
    )


def pending_buy_exposure_value(open_orders: list[dict], symbol: str, price: float) -> float:
    """Dollar value of not-yet-filled buy orders for `symbol`. Positions only reflect fills,
    so a cycle that runs again before a prior order fills (e.g. market closed, day order still
    queued) would otherwise see zero exposure and keep buying — this closes that gap by folding
    unfilled quantity into the same cap, priced at the current live quote."""
    symbol = symbol.strip().upper()
    unfilled_qty = sum(
        float(o.get("qty") or 0) - float(o.get("filled_qty") or 0)
        for o in open_orders
        if (o.get("symbol") or "").strip().upper() == symbol and o.get("side") == "buy"
    )
    return max(0.0, unfilled_qty) * price


def clamp_to_exposure_cap_value(existing_exposure_value: float, requested_usd: float, max_symbol_exposure_usd: float) -> float:
    room = max_symbol_exposure_usd - existing_exposure_value
    if room <= 0:
        return 0.0
    return max(0.0, min(requested_usd, room))


def round_quantity(qty: float, fractionable: bool) -> float:
    if qty <= 0:
        return 0.0
    if fractionable:
        return round(qty, 6)
    return float(int(qty))
