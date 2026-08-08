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
