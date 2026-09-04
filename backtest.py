"""Backtests the ML trading strategy (train_model.py + ml_decision.py's decision policy) against
historical data — simulating what the deployed bot would actually have done, not just how
accurate the model's raw predictions are.

Usage:
    python3 backtest.py [--starting-cash 100000] [--history-days 730]

The model is trained ONLY on the chronological "train" slice — the same time-based split
train_model.py's evaluate_time_split() uses for its own honest evaluation — then walked forward
day by day through the held-out "test" slice, so every simulated decision is made by a model that
never saw that day's data during training. Each day applies the exact same buy/sell/hold priority
policy ml_decision.get_ml_decision() uses live (manage held positions' sell signals first, then
the highest-confidence new buy, else hold) and the exact same risk.py sizing/exposure/position-
count caps run.py enforces, so the resulting equity curve reflects the actual deployed bot's
behavior, not an idealized version of it.

Simplifications vs. live trading (worth knowing, not hidden):
  - One decision per trading day — matches the model's actual signal cadence (its indicators are
    all daily-bar-based regardless of how often run.py's cycle fires), rather than every ~15 min.
  - A day's decision (made from that day's close-derived features) executes at the *next* trading
    day's open price — avoids feeding the model a price it couldn't have actually traded at.
  - Only days the stock market is open are simulated, mirroring run.py's own market-hours skip
    (which also pauses crypto management on weekends/holidays in live trading).
  - Every symbol is treated as fractionable; real fractionability varies by Alpaca asset.
  - No slippage or commission modeled (Alpaca charges neither on these order types).
  - A buy is skipped outright (rather than partially filled) if it would exceed available cash.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier

from alpaca_client import AlpacaClient, AlpacaError, is_crypto
from config import Config, ConfigError
from features import FEATURE_COLUMNS, bars_to_frame, compute_indicators
from risk import blocks_new_symbol, clamp_order_value, clamp_to_exposure_cap_value, round_quantity
from train_model import (
    BUY_THRESHOLD,
    HISTORY_DAYS,
    LABEL_HORIZON_DAYS,
    SELL_THRESHOLD,
    TEST_HOLDOUT_FRACTION,
    evaluate_time_split,
    label_from_forward_return,
)

# Sentinel buy/sell size ml_decision.py hands run.py — clamp_order_value/clamp_to_exposure_cap_value
# always cut it down to the configured caps, same as live.
SENTINEL_AMOUNT_USD = 1_000_000_000.0


def fetch_symbol_data(alpaca: AlpacaClient, symbol: str, start: str) -> dict | None:
    """Returns {"bars": OHLCV frame, "predict_feats": feature rows usable for a live-style
    prediction (NaN-feature warmup rows dropped, but NOT dropped just for lacking a future label —
    unlike training data, a prediction only needs the feature values, not a forward return),
    "labeled": feature rows + forward_return + label, for training only}, or None if there isn't
    enough history."""
    try:
        bars = alpaca.get_bars(symbol, "1Day", start=start)
    except AlpacaError as e:
        print(f"  {symbol}: could not fetch bars ({e}) — skipping", file=sys.stderr)
        return None
    df = bars_to_frame(bars)
    if len(df) < 60:
        print(f"  {symbol}: only {len(df)} bars, too little history — skipping", file=sys.stderr)
        return None

    feats = compute_indicators(df, is_crypto_symbol=is_crypto(symbol))
    predict_feats = feats.dropna()

    forward_return = df["close"].shift(-LABEL_HORIZON_DAYS) / df["close"] - 1
    labeled = feats.copy()
    labeled["forward_return"] = forward_return
    labeled = labeled.dropna()
    labeled["label"] = labeled["forward_return"].apply(label_from_forward_return)
    labeled["symbol"] = symbol

    print(f"  {symbol}: {len(df)} bars -> {len(predict_feats)} predictable rows, "
          f"{len(labeled)} labeled rows")
    return {"bars": df, "predict_feats": predict_feats, "labeled": labeled}


def simulate(
    watchlist: list[str],
    data: dict[str, dict],
    model: GradientBoostingClassifier,
    trading_days: pd.DatetimeIndex,
    starting_cash: float,
    max_order_value_usd: float,
    max_symbol_exposure_usd: float,
    max_concurrent_positions: int,
) -> dict:
    """Walks trading_days in order, executing at each day's open any action decided the prior day,
    then marking equity to that day's close, then deciding today's action (executed next day)."""
    cash = starting_cash
    open_positions: dict[str, dict] = {}  # symbol -> {"qty", "entry_price", "entry_date"}
    equity_curve: list[tuple] = []
    trades: list[dict] = []
    pending_action: dict | None = None

    def latest_close(symbol: str, day) -> float | None:
        bars = data[symbol]["bars"]
        if day in bars.index:
            return float(bars.loc[day, "close"])
        prior = bars.index[bars.index <= day]
        return float(bars.loc[prior[-1], "close"]) if len(prior) else None

    for i, day in enumerate(trading_days):
        # 1. Execute yesterday's decision at today's open.
        if pending_action is not None:
            action, symbol = pending_action["action"], pending_action["symbol"]
            bars = data[symbol]["bars"]
            if day in bars.index:
                exec_price = float(bars.loc[day, "open"])
                if action == "sell" and symbol in open_positions:
                    pos = open_positions.pop(symbol)
                    proceeds = pos["qty"] * exec_price
                    cash += proceeds
                    pnl = pos["qty"] * (exec_price - pos["entry_price"])
                    trades.append({
                        "action": "sell", "symbol": symbol, "qty": pos["qty"],
                        "price": exec_price, "date": str(day.date()), "pnl": pnl,
                        "held_days": (day - pos["entry_date"]).days,
                    })
                elif action == "buy" and symbol not in open_positions:
                    order_usd = clamp_order_value(SENTINEL_AMOUNT_USD, max_order_value_usd)
                    order_usd = clamp_to_exposure_cap_value(0.0, order_usd, max_symbol_exposure_usd)
                    order_usd = min(order_usd, cash)
                    qty = round_quantity(order_usd / exec_price, fractionable=True)
                    cost = qty * exec_price
                    if qty > 0 and cost <= cash:
                        cash -= cost
                        open_positions[symbol] = {"qty": qty, "entry_price": exec_price, "entry_date": day}
                        trades.append({
                            "action": "buy", "symbol": symbol, "qty": qty,
                            "price": exec_price, "date": str(day.date()),
                        })
            pending_action = None

        # 2. Mark equity to today's close, post-execution.
        equity = cash + sum(
            pos["qty"] * (latest_close(sym, day) or pos["entry_price"])
            for sym, pos in open_positions.items()
        )
        equity_curve.append((day, equity))

        # 3. Decide today's action (executes at the next day's open, on the next loop iteration).
        held = set(open_positions.keys())
        predictions = {}
        for symbol in watchlist:
            feats = data[symbol]["predict_feats"]
            if day not in feats.index:
                continue
            row = feats.loc[[day]]
            proba = dict(zip(model.classes_, model.predict_proba(row[FEATURE_COLUMNS])[0]))
            predictions[symbol] = {"label": max(proba, key=proba.get), "proba": proba}

        sell_candidates = {s: p for s, p in predictions.items() if s in held and p["label"] == "sell"}
        if sell_candidates:
            symbol = max(sell_candidates, key=lambda s: sell_candidates[s]["proba"]["sell"])
            pending_action = {"action": "sell", "symbol": symbol}
            continue
        buy_candidates = {s: p for s, p in predictions.items() if s not in held and p["label"] == "buy"}
        if buy_candidates:
            symbol = max(buy_candidates, key=lambda s: buy_candidates[s]["proba"]["buy"])
            if not blocks_new_symbol(held, symbol, max_concurrent_positions):
                pending_action = {"action": "buy", "symbol": symbol}
            # else: at the position cap — matches run.py's blocks_new_symbol rejection, hold instead.

    return {"equity_curve": equity_curve, "trades": trades, "open_positions": open_positions, "final_cash": cash}


def compute_metrics(equity_curve: list[tuple], trades: list[dict]) -> dict:
    equity = pd.Series([e for _, e in equity_curve], index=[d for d, _ in equity_curve])
    daily_returns = equity.pct_change().dropna()

    running_max = equity.cummax()
    drawdown = equity / running_max - 1
    max_drawdown = drawdown.min()

    total_return = equity.iloc[-1] / equity.iloc[0] - 1
    n_days = len(equity)
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (252 / n_days) - 1 if n_days > 1 else 0.0
    sharpe = (
        (daily_returns.mean() / daily_returns.std()) * (252 ** 0.5)
        if daily_returns.std() > 0 else 0.0
    )

    closed = [t for t in trades if t["action"] == "sell"]
    wins = [t for t in closed if t["pnl"] > 0]
    win_rate = len(wins) / len(closed) if closed else 0.0
    total_pnl = sum(t["pnl"] for t in closed)

    return {
        "start_equity": equity.iloc[0], "end_equity": equity.iloc[-1],
        "total_return": total_return, "cagr": cagr, "max_drawdown": max_drawdown, "sharpe": sharpe,
        "n_trades": len(closed), "win_rate": win_rate, "total_realized_pnl": total_pnl,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest the ML trading strategy against historical data.")
    parser.add_argument("--starting-cash", type=float, default=100_000.0)
    parser.add_argument("--history-days", type=int, default=HISTORY_DAYS)
    parser.add_argument("--output", default="backtest_equity.csv", help="Path to write the daily equity curve.")
    args = parser.parse_args()

    try:
        config = Config()
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 1

    watchlist = config.watchlist
    alpaca = AlpacaClient(
        config.alpaca_base_url, config.alpaca_data_url, config.alpaca_api_key_id, config.alpaca_api_secret_key
    )

    start = (datetime.now(timezone.utc) - timedelta(days=args.history_days)).strftime("%Y-%m-%d")
    print(f"Fetching {args.history_days} days of history for {len(watchlist)} symbols: {', '.join(watchlist)}")
    data = {}
    for symbol in watchlist:
        result = fetch_symbol_data(alpaca, symbol, start)
        if result is not None:
            data[symbol] = result
    if not data:
        print("No usable data for any watchlist symbol.", file=sys.stderr)
        return 1

    all_labeled = pd.concat([d["labeled"] for d in data.values()]).sort_index()
    cutoff_dates = all_labeled.index.unique().sort_values()
    cutoff = cutoff_dates[int(len(cutoff_dates) * (1 - TEST_HOLDOUT_FRACTION))]
    train = all_labeled[all_labeled.index < cutoff]
    if train.empty:
        print("Not enough history before the test cutoff to train on.", file=sys.stderr)
        return 1

    print(f"\nTraining on {len(train)} rows before {cutoff.date()}; simulating from {cutoff.date()} forward.\n")
    print("--- Model quality on the same held-out slice (classification view) ---")
    evaluate_time_split(all_labeled)

    model = GradientBoostingClassifier(random_state=0)
    model.fit(train[FEATURE_COLUMNS], train["label"])

    # Canonical trading calendar: a stock symbol's own trading days (skips weekends/holidays),
    # matching run.py's own market-hours skip, which pauses the whole cycle — crypto included —
    # whenever the stock market is shut.
    stock_symbols = [s for s in watchlist if not is_crypto(s) and s in data]
    calendar_symbol = stock_symbols[0] if stock_symbols else next(iter(data))
    all_days = data[calendar_symbol]["bars"].index
    trading_days = all_days[(all_days >= cutoff) & (all_days <= all_days.max())]
    if len(trading_days) < 2:
        print("Not enough held-out trading days to simulate.", file=sys.stderr)
        return 1

    print(f"\n--- Trading simulation: {len(trading_days)} trading days "
          f"({trading_days[0].date()} to {trading_days[-1].date()}) ---")
    result = simulate(
        watchlist, data, model, trading_days, args.starting_cash,
        config.max_order_value_usd, config.max_symbol_exposure_usd, config.max_concurrent_positions,
    )
    metrics = compute_metrics(result["equity_curve"], result["trades"])

    print(f"\nStarting cash: ${args.starting_cash:,.2f}")
    print(f"Ending equity: ${metrics['end_equity']:,.2f}  "
          f"({'+' if metrics['total_return'] >= 0 else ''}{metrics['total_return']:.1%} total return)")
    print(f"Annualized (CAGR-style over the test window): {metrics['cagr']:+.1%}")
    print(f"Max drawdown: {metrics['max_drawdown']:.1%}")
    print(f"Sharpe (rf=0, daily->annualized): {metrics['sharpe']:.2f}")
    print(f"Closed trades: {metrics['n_trades']}  |  win rate: {metrics['win_rate']:.0%}  "
          f"|  total realized P&L: ${metrics['total_realized_pnl']:+,.2f}")
    if result["open_positions"]:
        held_desc = ", ".join(f"{s} ({p['qty']:g} @ ${p['entry_price']:,.2f})" for s, p in result["open_positions"].items())
        print(f"Still open at end of window (marked to last close in ending equity): {held_desc}")

    # Simple buy-and-hold benchmark for context, if SPY is in the watchlist.
    if "SPY" in data:
        spy_bars = data["SPY"]["bars"]
        spy_window = spy_bars[(spy_bars.index >= trading_days[0]) & (spy_bars.index <= trading_days[-1])]
        if len(spy_window) >= 2:
            spy_return = spy_window["close"].iloc[-1] / spy_window["close"].iloc[0] - 1
            print(f"\nFor context — SPY buy-and-hold over the same window: {spy_return:+.1%}")

    equity_df = pd.DataFrame(result["equity_curve"], columns=["date", "equity"])
    equity_df.to_csv(args.output, index=False)
    print(f"\nDaily equity curve written to {args.output} ({len(equity_df)} rows).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
