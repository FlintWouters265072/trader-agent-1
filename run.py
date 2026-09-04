import argparse
import json
import sys
from datetime import datetime, timezone

from alpaca_client import AlpacaClient, AlpacaError, normalize_crypto_symbol
from config import Config, ConfigError
from ml_decision import MLDecisionError, get_ml_decision
from risk import (
    blocks_new_symbol,
    clamp_order_value,
    clamp_to_exposure_cap_value,
    held_quantity,
    open_symbol_set,
    pending_buy_exposure_value,
    pending_sell_quantity,
    round_quantity,
    summarize_positions,
    total_exposure_value,
)

LOG_PATH = "decisions.jsonl"


def log_entry(entry: dict) -> None:
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def quote_price(quote: dict) -> float:
    ap = quote.get("ap") or 0
    bp = quote.get("bp") or 0
    if ap and bp:
        return (ap + bp) / 2
    return ap or bp or 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Alpaca paper-trading ML trading agent — one decision cycle.")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually place the order on Alpaca paper trading. Without this flag, the agent only logs its decision.",
    )
    args = parser.parse_args()

    try:
        config = Config()
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 1

    execute = config.execute or args.execute

    print(
        "Risk settings: "
        f"max_order_value_usd={config.max_order_value_usd:g} | "
        f"max_symbol_exposure_usd={config.max_symbol_exposure_usd:g} | "
        f"max_concurrent_positions={config.max_concurrent_positions} | "
        f"watchlist={','.join(config.watchlist)}"
    )

    alpaca = AlpacaClient(
        config.alpaca_base_url, config.alpaca_data_url, config.alpaca_api_key_id, config.alpaca_api_secret_key
    )

    try:
        clock = alpaca.get_clock()
    except AlpacaError as e:
        print(f"Alpaca API error while fetching market clock: {e}", file=sys.stderr)
        return 1

    if not clock.get("is_open"):
        print(f"Market is closed (next open: {clock.get('next_open')}) — skipping this cycle, no decision made.")
        return 0

    try:
        positions = alpaca.get_positions()
        for p in positions:
            p["symbol"] = normalize_crypto_symbol(p.get("symbol", ""), p.get("asset_class"))

        quotes = {}
        for p in positions:
            symbol = p.get("symbol")
            if not symbol:
                continue
            try:
                quotes[symbol] = alpaca.get_quote(symbol)
            except AlpacaError as e:
                print(f"Warning: quote fetch failed for held position {symbol}: {e}", file=sys.stderr)
    except AlpacaError as e:
        print(f"Alpaca API error while fetching data: {e}", file=sys.stderr)
        return 1

    try:
        open_orders = alpaca.get_orders(status="open")
        for o in open_orders:
            o["symbol"] = normalize_crypto_symbol(o.get("symbol", ""), o.get("asset_class"))
    except AlpacaError as e:
        print(f"Warning: could not fetch open orders, exposure/sell sizing may be off: {e}", file=sys.stderr)
        open_orders = []

    position_summaries = summarize_positions(positions)
    open_symbols = open_symbol_set(position_summaries, open_orders)

    try:
        decision = get_ml_decision(alpaca, position_summaries, config.watchlist, config.model_path)
    except MLDecisionError as e:
        print(f"No decision this cycle: {e}", file=sys.stderr)
        return 0

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "executed": False,
    }

    if decision["action"] == "hold":
        decision["quantity"] = 0
        print(f"HOLD — {decision['rationale']}")
        log_entry(entry)
        return 0

    symbol = decision["symbol"].strip().upper()
    if not symbol:
        print("Model gave an empty symbol — nothing to do.", file=sys.stderr)
        entry["reject_reason"] = "empty_symbol"
        log_entry(entry)
        return 1

    try:
        asset = alpaca.get_asset(symbol)
    except AlpacaError as e:
        print(f"Model suggested {symbol}, which Alpaca doesn't recognize — refusing to trade. ({e})", file=sys.stderr)
        entry["reject_reason"] = "symbol_not_recognized"
        log_entry(entry)
        return 1

    # Alpaca's asset lookup accepts a crypto symbol with or without the '/' and always answers
    # with the canonical (slashed) form — adopt it so every lookup below (quotes, exposure math,
    # order placement) agrees on one symbol, even on the rare cycle where the model echoes back
    # the raw no-slash form a held position was originally shown as before positions/orders were
    # normalized on fetch.
    symbol = asset.get("symbol") or symbol
    # Log the canonical form too, so decisions.jsonl and the dashboard name the same symbol the
    # order was actually placed for, instead of whichever variant the model happened to type.
    decision["symbol"] = symbol

    if not asset.get("tradable"):
        print(f"{symbol} is not currently tradable on Alpaca — refusing to trade.", file=sys.stderr)
        entry["reject_reason"] = "symbol_not_tradable"
        log_entry(entry)
        return 1

    quote = quotes.get(symbol)
    if quote is None:
        try:
            quote = alpaca.get_quote(symbol)
        except AlpacaError as e:
            print(f"Could not fetch a quote for {symbol}: {e}", file=sys.stderr)
            entry["reject_reason"] = "quote_not_available"
            log_entry(entry)
            return 1

    price = quote_price(quote)
    if price <= 0:
        print(f"No usable live price for {symbol} — refusing to trade.", file=sys.stderr)
        entry["reject_reason"] = "no_price"
        log_entry(entry)
        return 1

    requested_usd = decision["amount_usd"]
    order_usd = clamp_order_value(requested_usd, config.max_order_value_usd)
    existing_exposure_value = total_exposure_value(position_summaries, symbol)

    fractionable = asset.get("fractionable", False)

    if decision["action"] == "buy":
        if blocks_new_symbol(open_symbols, symbol, config.max_concurrent_positions):
            print(
                f"{symbol} would be a new position, but {len(open_symbols)}/{config.max_concurrent_positions} "
                f"concurrent positions are already open — refusing to open it. Still free to add to an "
                f"existing symbol or sell/reduce anything held."
            )
            order_usd = 0.0
            entry["reject_reason"] = "max_concurrent_positions"
        else:
            existing_exposure_value += pending_buy_exposure_value(open_orders, symbol, price)
            order_usd = clamp_to_exposure_cap_value(existing_exposure_value, order_usd, config.max_symbol_exposure_usd)
        quantity = round_quantity(order_usd / price, fractionable)
    else:
        # Never sell more than what's actually held and not already reserved by a still-unfilled
        # sell order — avoids both accidentally opening a short and re-requesting shares a prior
        # queued order (e.g. illiquid/halted quote) already holds, which Alpaca rejects with a 403.
        sellable_qty = max(0.0, held_quantity(position_summaries, symbol) - pending_sell_quantity(open_orders, symbol))
        # Compare in share units rather than dollars: clamping dollars and dividing back out by
        # price sends the quantity through a float round-trip that does not reproduce it exactly,
        # landing either a hair above the held quantity (Alpaca rejects the whole order with a 403)
        # or a whole share below it (7 shares of a $19.99 stock sells 6, stranding the last one).
        if order_usd / price >= sellable_qty:
            # Closing the position: send exactly what's held. Rounding to the venue's precision
            # here would strand sub-precision dust that no later cycle can sell (it rounds to
            # zero), while still occupying one of the MAX_CONCURRENT_POSITIONS slots forever.
            quantity = sellable_qty
        else:
            quantity = round_quantity(order_usd / price, fractionable)

    if requested_usd != round(quantity * price, 2):
        entry["model_requested_usd"] = requested_usd
    entry["decision"]["quantity"] = quantity
    entry["order_usd"] = round(quantity * price, 2)

    if quantity <= 0:
        print(f"Order size clamped to 0 (risk limits, nothing held to sell, or rounding) — nothing to do. Rationale: {decision['rationale']}")
        log_entry(entry)
        return 0

    side = "buy" if decision["action"] == "buy" else "sell"
    print(f"{decision['action'].upper()} {quantity} {symbol} (~${entry['order_usd']:.2f}) — {decision['rationale']}")

    if not execute:
        print("Dry run (EXECUTE=false, no --execute flag): order NOT placed.")
        log_entry(entry)
        return 0

    try:
        order_result = alpaca.place_order(symbol, side, quantity)
        print("Order placed:", json.dumps(order_result, indent=2))
        entry["executed"] = True
        entry["order_result"] = order_result
    except AlpacaError as e:
        print(f"Order failed: {e}", file=sys.stderr)
        entry["executed"] = False
        entry["order_error"] = str(e)
        log_entry(entry)
        return 1

    log_entry(entry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
