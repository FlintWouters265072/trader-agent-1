"""Live decision-making via the trained classifier (train_model.py), replacing the old Claude
call. get_ml_decision() returns the exact same {action, symbol, amount_usd, rationale} shape the
LLM path used to, so run.py's downstream sizing, risk checks, and order placement are unchanged.

Policy, mirroring what the old system prompt asked the LLM to do:
  1. Manage existing positions first: if any watchlist symbol currently held has a "sell" signal,
     sell the strongest one — closing a bad position is at least as important as opening a new one.
  2. Otherwise, open the highest-confidence "buy" signal among watchlist symbols not already held
     (prefers diversification over piling into one name, like the old prompt's rule did).
  3. Otherwise, hold.

The model only ever sees symbols in the watchlist it was trained on — a position left over from
before this conversion (something the old LLM opened that isn't on the current watchlist) has no
trained signal and is left alone rather than guessed at.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import joblib

from alpaca_client import AlpacaClient, AlpacaError, is_crypto
from features import FEATURE_COLUMNS, MIN_BARS_REQUIRED, bars_to_frame, compute_indicators

# Calendar days of history fetched per symbol per cycle — comfortably more than MIN_BARS_REQUIRED
# trading days once weekends/holidays are accounted for, without hammering the bars endpoint.
INFERENCE_LOOKBACK_DAYS = 120


class MLDecisionError(RuntimeError):
    """No usable decision this cycle — e.g. the model file is missing or stale. Always transient
    from the caller's point of view (the next cycle re-tries), so run.py skips the cycle rather
    than crashing, matching the old DecisionError contract for API failures."""


def load_model(model_path: str) -> dict:
    try:
        return joblib.load(model_path)
    except FileNotFoundError as e:
        raise MLDecisionError(f"{model_path} not found — run train_model.py first") from e
    except Exception as e:  # noqa: BLE001 - a corrupt/incompatible joblib file is not worth typing precisely
        raise MLDecisionError(f"could not load {model_path}: {e}") from e


def latest_prediction(alpaca: AlpacaClient, symbol: str, model_bundle: dict) -> dict | None:
    """Fetches recent bars for `symbol` and returns {"label", "proba"} for the most recent bar,
    or None if there isn't enough history to compute the full feature set yet."""
    start = (datetime.now(timezone.utc) - timedelta(days=INFERENCE_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    try:
        bars = alpaca.get_bars(symbol, "1Day", start=start)
    except AlpacaError:
        return None
    df = bars_to_frame(bars)
    if len(df) < MIN_BARS_REQUIRED:
        return None

    feats = compute_indicators(df, is_crypto_symbol=is_crypto(symbol))
    latest = feats.iloc[[-1]]
    if latest.isna().any(axis=None):
        return None

    model = model_bundle["model"]
    # No strict=: model.classes_ and the predict_proba row it pairs with come from the same
    # sklearn call and are always equal length; strict= is 3.10+ syntax the deployed 3.9
    # interpreter rejects with a TypeError.
    proba = dict(zip(model.classes_, model.predict_proba(latest[FEATURE_COLUMNS])[0]))
    label = max(proba, key=proba.get)
    return {"label": label, "proba": proba, "latest_row": latest.iloc[0]}


def held_watchlist_symbols(position_summaries: list[dict], watchlist: list[str]) -> set[str]:
    watchlist_set = {s.upper() for s in watchlist}
    return {
        (p.get("symbol") or "").upper()
        for p in position_summaries
        if (p.get("amount") or 0) != 0 and (p.get("symbol") or "").upper() in watchlist_set
    }


def rationale_for(symbol: str, pred: dict) -> str:
    proba_str = ", ".join(f"P({k})={v:.2f}" for k, v in sorted(pred["proba"].items(), key=lambda kv: -kv[1]))
    row = pred["latest_row"]
    return (
        f"ML model: {pred['label'].upper()} signal on {symbol} ({proba_str}). "
        f"RSI14={row['rsi14']:.1f}, MACD hist={row['macd_hist']:+.3f}, "
        f"20d momentum={row['momentum20']:+.1%}, 20d volatility={row['volatility20']:.1%}."
    )


def get_ml_decision(alpaca: AlpacaClient, position_summaries: list[dict], watchlist: list[str], model_path: str) -> dict:
    model_bundle = load_model(model_path)
    held = held_watchlist_symbols(position_summaries, watchlist)

    predictions: dict[str, dict] = {}
    for symbol in watchlist:
        pred = latest_prediction(alpaca, symbol, model_bundle)
        if pred is not None:
            predictions[symbol] = pred

    if not predictions:
        raise MLDecisionError("could not compute a prediction for any watchlist symbol this cycle")

    # 1. Manage existing positions: sell the strongest "sell" signal among what's actually held.
    sell_candidates = {s: p for s, p in predictions.items() if s in held and p["label"] == "sell"}
    if sell_candidates:
        symbol, pred = max(sell_candidates.items(), key=lambda kv: kv[1]["proba"]["sell"])
        return {
            "action": "sell", "symbol": symbol,
            # A sentinel well above any realistic position value — risk.py's sell-sizing already
            # caps this to exactly what's held (see run.py), so this only needs to say "close it".
            "amount_usd": 1_000_000_000.0,
            "rationale": rationale_for(symbol, pred),
        }

    # 2. Otherwise open the highest-confidence "buy" signal among symbols not already held.
    buy_candidates = {s: p for s, p in predictions.items() if s not in held and p["label"] == "buy"}
    if buy_candidates:
        symbol, pred = max(buy_candidates.items(), key=lambda kv: kv[1]["proba"]["buy"])
        return {
            "action": "buy", "symbol": symbol,
            # Also a sentinel — run.py's clamp_order_value / clamp_to_exposure_cap_value always
            # cut this down to the configured MAX_ORDER_VALUE_USD / MAX_SYMBOL_EXPOSURE_USD.
            "amount_usd": 1_000_000_000.0,
            "rationale": rationale_for(symbol, pred),
        }

    # 3. Nothing to do.
    hold_symbol = next(iter(held), "")
    if hold_symbol:
        pred = predictions.get(hold_symbol)
        rationale = rationale_for(hold_symbol, pred) if pred else f"Holding {hold_symbol}; no prediction available this cycle."
    else:
        rationale = "No sell signal on anything held and no buy signal on any watchlist symbol not already held."
    return {"action": "hold", "symbol": hold_symbol, "amount_usd": 0.0, "rationale": rationale}
