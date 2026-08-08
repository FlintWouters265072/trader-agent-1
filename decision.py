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

SYSTEM_PROMPT = """You are an active, opportunity-seeking trading decision assistant for a \
paper-trading (simulation) account on Alpaca. Given the current account state and open positions \
(with their live unrealized P&L and current quotes), decide on exactly one action: buy, sell, or hold.

You are NOT restricted to a fixed watchlist. You may:
- Buy any actively-traded US-listed stock or ETF by its ticker symbol (e.g. "AAPL", "SPY").
- Buy any USD-quoted crypto pair Alpaca supports, written as "BASE/USD" (e.g. "BTC/USD", "ETH/USD").
- Sell/reduce any symbol you currently hold (shown in Open Positions below).

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


def build_prompt(account: dict, positions: list[dict], quotes: dict[str, dict]) -> str:
    lines = ["## Account", json.dumps(account, indent=2)]
    lines.append("\n## Open Positions (with live quotes below — evaluate whether each is still worth holding)")
    position_summaries = summarize_positions(positions)
    if position_summaries:
        lines.append(json.dumps(position_summaries, indent=2))
    else:
        lines.append("None.")

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


def get_decision(prompt: str, api_key: str) -> dict:
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        output_config={"format": {"type": "json_schema", "schema": DECISION_SCHEMA}},
    )
    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text)
