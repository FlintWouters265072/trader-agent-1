from __future__ import annotations

import json

import anthropic

MODEL = "claude-haiku-4-5"

DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["buy", "sell", "hold"]},
        "symbol": {"type": "string"},
        "amount_usd": {"type": "number"},
        "rationale": {"type": "string"},
    },
    "required": ["action", "symbol", "amount_usd", "rationale"],
    "additionalProperties": False,
}

SYSTEM_PROMPT_TEMPLATE = """You are an active, opportunity-seeking trading decision assistant for a \
paper-trading (simulation) account on Alpaca. Given the current account state and open positions \
(with their live unrealized P&L and current quotes), decide on exactly one action: buy, sell, or hold.

You are NOT restricted to a fixed watchlist. You may:
- Buy any actively-traded US-listed stock or ETF by its ticker symbol (e.g. "AAPL", "SPY").
- Buy any USD-quoted crypto pair Alpaca supports, written as "BASE/USD" (e.g. "BTC/USD", "ETH/USD").
- Sell/reduce any symbol you currently hold (shown in Open Positions below).

{risk_appetite_guidance}

Rules:
- Size every buy/sell as a dollar amount in "amount_usd" — the exact share/coin quantity is \
computed afterward from the live price, so don't try to guess share counts yourself.
- A brand-new symbol you don't currently hold has no live quote in this prompt — that's expected. \
Use your general knowledge of the company/asset to justify picking it; a live quote will be fetched \
and used to size and validate the order before anything is placed. If the symbol turns out not to be \
tradable on Alpaca, the cycle is simply logged as rejected — that's fine, just make a reasonable pick.
- Default to acting. Use any reasonable basis (recent context, sector view, existing position \
performance) to justify a buy or sell — "hold" is for when there is genuinely nothing to react to, \
not a safe default when unsure.
- Actively manage existing positions, not just new entries. For every open position, weigh its \
unrealized P&L and current price against why it was likely opened. If a position looks no longer \
profitable or its thesis has soured, decide "sell" to close or reduce it — closing a bad position is \
just as valid as opening a new one. To fully close a position, set "amount_usd" to at least its full \
current market value (amount * current_price) — it will be capped to what's actually held.
- "rationale" must briefly explain the reasoning in plain language, and should say explicitly \
whether each existing position was considered and why it was kept, closed, or reduced.
- Don't over-concentrate in a single symbol — prefer opening a new position over adding to one you \
already hold, unless the existing position clearly needs attention (meaningful loss, or a genuinely \
better opportunity to add).
- If action is "hold", set symbol to a position you considered (or "" if none held) and amount_usd to 0."""

# Purely a prompt-level style knob — steers WHAT KIND of assets get picked, never the dollar/count
# sizing rules above (those come from risk.py/config.py and apply identically at every level).
RISK_APPETITE_GUIDANCE = {
    "low": (
        "Risk appetite: LOW. Prioritize capital preservation over growth. Prefer large-cap, "
        "well-established, liquid names and broad-market/diversified ETFs (e.g. SPY, VOO, VTI, QQQ) "
        "over individual speculative stocks. Avoid small-cap, pre-profit, highly volatile, or "
        "thinly-traded names. Avoid or minimize crypto — if used at all, keep it a small allocation "
        "in major coins (BTC/USD, ETH/USD) only. Favor steady, modest, lower-volatility returns over "
        "high-upside bets."
    ),
    "medium": (
        "Risk appetite: MEDIUM. Balance growth and stability. A mix of established large/mid-cap "
        "growth companies and some diversified ETF exposure is appropriate. Moderate volatility is "
        "acceptable in pursuit of above-market returns. Major crypto (BTC/USD, ETH/USD) can be used "
        "as part of a diversified allocation, not the majority of it."
    ),
    "high": (
        "Risk appetite: HIGH. Actively seek higher-growth, higher-volatility opportunities in pursuit "
        "of outsized returns — smaller-cap growth names, high-beta tech, emerging themes, and momentum "
        "plays are all fair game, not just blue-chip defensives. Larger crypto allocations (including "
        "altcoins Alpaca supports) are acceptable. You should be willing to accept larger drawdowns "
        "and concentrated, high-conviction bets in exchange for higher expected return — don't default "
        "to the safe, diversified choice just because it's safe."
    ),
}


def build_system_prompt(risk_appetite: str) -> str:
    guidance = RISK_APPETITE_GUIDANCE.get((risk_appetite or "").strip().lower(), RISK_APPETITE_GUIDANCE["medium"])
    return SYSTEM_PROMPT_TEMPLATE.format(risk_appetite_guidance=guidance)


def summarize_positions(positions: list[dict]) -> list[dict]:
    summaries = []
    for p in positions:
        side = p.get("side", "long")
        qty = float(p.get("qty", 0))
        summaries.append({
            "symbol": p.get("symbol", ""),
            "amount": -qty if side == "short" else qty,
            "open_price": float(p.get("avg_entry_price", 0) or 0),
            "current_price": float(p.get("current_price", 0) or 0),
            "unrealized_pl_in_base_currency": float(p.get("unrealized_pl", 0) or 0),
        })
    return summaries


def summarize_open_orders(open_orders: list[dict]) -> list[dict]:
    summaries = []
    for o in open_orders:
        summaries.append({
            "symbol": o.get("symbol", ""),
            "side": o.get("side", ""),
            "qty": float(o.get("qty", 0) or 0),
            "filled_qty": float(o.get("filled_qty", 0) or 0),
            "status": o.get("status", ""),
            "submitted_at": o.get("submitted_at", ""),
        })
    return summaries


def build_prompt(
    account: dict,
    positions: list[dict],
    quotes: dict[str, dict],
    open_orders: list[dict] | None = None,
    open_position_count: int | None = None,
    max_concurrent_positions: int | None = None,
) -> str:
    lines = ["## Account", json.dumps(account, indent=2)]
    lines.append("\n## Open Positions (with live quotes below — evaluate whether each is still worth holding)")
    position_summaries = summarize_positions(positions)
    if position_summaries:
        lines.append(json.dumps(position_summaries, indent=2))
    else:
        lines.append("None.")

    if open_position_count is not None and max_concurrent_positions is not None:
        if open_position_count >= max_concurrent_positions:
            lines.append(
                f"\n## Position Capacity: {open_position_count}/{max_concurrent_positions} — FULL. "
                "Opening any symbol not already held or on order above will be rejected outright — the "
                "order gets clamped to zero and nothing happens. Do NOT propose a new symbol. Either add "
                "to / trim an existing position, sell one to free a slot for something you'd rather hold, "
                "or hold."
            )
        else:
            lines.append(
                f"\n## Position Capacity: {open_position_count}/{max_concurrent_positions} — "
                f"{max_concurrent_positions - open_position_count} slot(s) free for a new symbol."
            )

    order_summaries = summarize_open_orders(open_orders or [])
    if order_summaries:
        lines.append(
            "\n## Pending Orders (submitted but NOT yet filled — shares in a pending sell are already "
            "reserved and cannot be sold again; a pending buy already counts toward exposure. Do not "
            "propose an action this pending order already covers.)"
        )
        lines.append(json.dumps(order_summaries, indent=2))

    if quotes:
        lines.append("\n## Live Quotes For Open Positions")
        for symbol, quote in quotes.items():
            lines.append(f"\n### {symbol}")
            lines.append(json.dumps(quote, indent=2))

    lines.append(
        "\nBased on the above, what single action should be taken right now? You may act on an "
        "existing position above, or name any new US-listed stock/ETF ticker or Alpaca USD crypto "
        "pair to open a fresh position in. Remember to explicitly consider closing or reducing any "
        "open position that no longer looks profitable, not just whether to open a new one."
    )
    return "\n".join(lines)


class DecisionError(RuntimeError):
    """The model produced no usable decision this cycle. Always transient from the caller's
    point of view — the next cycle re-asks from scratch — so run.py skips the cycle rather
    than crashing the container with a traceback."""


def get_decision(prompt: str, api_key: str, risk_appetite: str = "medium") -> dict:
    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=build_system_prompt(risk_appetite),
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": DECISION_SCHEMA}},
        )
    except anthropic.APIError as e:
        # Overload (529), rate limits, and connection drops are all routine on a loop that
        # runs every 15 minutes forever; the SDK already retried internally before raising.
        raise DecisionError(f"Anthropic API error: {e}") from e

    if response.stop_reason == "refusal":
        raise DecisionError("model declined to answer (stop_reason=refusal)")

    text = next((block.text for block in response.content if block.type == "text"), None)
    if text is None:
        raise DecisionError(f"no text block in response (stop_reason={response.stop_reason})")

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # Schema-constrained output still gets cut off mid-object if it hits max_tokens.
        hint = " — response hit max_tokens" if response.stop_reason == "max_tokens" else ""
        raise DecisionError(f"model returned unparseable JSON{hint}: {e}") from e
