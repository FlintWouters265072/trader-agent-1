import argparse
import json
import sys
from datetime import datetime, timezone

from alpaca_client import AlpacaClient, AlpacaError
from config import Config, ConfigError
from decision import build_prompt, get_decision, summarize_positions
from risk import (
    clamp_order_value,
    clamp_to_exposure_cap_value,
    pending_buy_exposure_value,
    round_quantity,
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
    parser = argparse.ArgumentParser(description="Alpaca paper-trading LLM trading agent — one decision cycle.")
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

    alpaca = AlpacaClient(
        config.alpaca_base_url, config.alpaca_data_url, config.alpaca_api_key_id, config.alpaca_api_secret_key
    )

    try:
        account = alpaca.get_account()
        positions = alpaca.get_positions()

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

    prompt = build_prompt(account, positions, quotes)
    decision = get_decision(prompt, config.anthropic_api_key)

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
    existing_exposure_value = total_exposure_value(summarize_positions(positions), symbol)

    if decision["action"] == "buy":
        try:
            open_orders = alpaca.get_orders(status="open")
        except AlpacaError as e:
            print(f"Warning: could not fetch open orders, exposure cap may undercount pending buys: {e}", file=sys.stderr)
            open_orders = []
        existing_exposure_value += pending_buy_exposure_value(open_orders, symbol, price)
        order_usd = clamp_to_exposure_cap_value(existing_exposure_value, order_usd, config.max_symbol_exposure_usd)
    else:
        # Never sell more than what's actually held — avoids accidentally opening a short.
        order_usd = min(order_usd, existing_exposure_value)

    quantity = round_quantity(order_usd / price, asset.get("fractionable", False))

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
