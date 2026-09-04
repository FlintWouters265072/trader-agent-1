"""Trains the buy/sell/hold classifier that ml_decision.py loads at cycle time.

Usage:
    python3 train_model.py

Fetches ~2 years of daily bars for every symbol in the watchlist (config.get_watchlist(), or the
WATCHLIST env var), builds technical-indicator features (features.py) and a forward-return label,
trains a GradientBoostingClassifier, prints an honest time-split evaluation, then refits on the
full dataset and saves model.joblib for ml_decision.py to load.

Re-run this after changing the watchlist, after changing FEATURE_COLUMNS in features.py, or
periodically to pick up more recent market data — nothing else needs to change for a retrain to
take effect on the next trading cycle.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

import joblib
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import classification_report

from alpaca_client import AlpacaClient, AlpacaError, is_crypto
from config import Config, ConfigError, get_watchlist
from features import FEATURE_COLUMNS, bars_to_frame, compute_indicators

HISTORY_DAYS = 730  # ~2 years of daily bars per symbol
LABEL_HORIZON_DAYS = 5  # look this many trading days ahead to label each row
BUY_THRESHOLD = 0.02  # forward return above this -> "buy"
SELL_THRESHOLD = -0.02  # forward return below this -> "sell"
TEST_HOLDOUT_FRACTION = 0.2  # most recent slice of dates, held out for honest evaluation
MODEL_PATH = "model.joblib"


def label_from_forward_return(r: float) -> str:
    if r > BUY_THRESHOLD:
        return "buy"
    if r < SELL_THRESHOLD:
        return "sell"
    return "hold"


def build_symbol_dataset(alpaca: AlpacaClient, symbol: str) -> pd.DataFrame | None:
    start = (datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)).strftime("%Y-%m-%d")
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
    forward_return = df["close"].shift(-LABEL_HORIZON_DAYS) / df["close"] - 1

    data = feats.copy()
    data["forward_return"] = forward_return
    data["symbol"] = symbol
    data = data.dropna()  # drops both the indicator warmup rows and the undated final label rows
    data["label"] = data["forward_return"].apply(label_from_forward_return)
    print(f"  {symbol}: {len(df)} bars -> {len(data)} labeled rows "
          f"({(data['label'] == 'buy').sum()} buy / {(data['label'] == 'sell').sum()} sell / "
          f"{(data['label'] == 'hold').sum()} hold)")
    return data


def evaluate_time_split(dataset: pd.DataFrame) -> None:
    """Chronological split, not random — a random split would leak future information into
    training (rows from the same symbol close in time share overlapping indicator windows and
    label horizons), which would make the reported accuracy meaningless as a live-performance
    estimate."""
    dataset = dataset.sort_index()
    cutoff = dataset.index.unique().sort_values()
    cutoff = cutoff[int(len(cutoff) * (1 - TEST_HOLDOUT_FRACTION))]
    train = dataset[dataset.index < cutoff]
    test = dataset[dataset.index >= cutoff]
    print(f"\nTime-split evaluation: train={len(train)} rows (before {cutoff.date()}), "
          f"test={len(test)} rows (from {cutoff.date()})")
    if train.empty or test.empty or test["label"].nunique() < 2:
        print("Not enough data on one side of the split to evaluate meaningfully — skipping.")
        return

    model = GradientBoostingClassifier(random_state=0)
    model.fit(train[FEATURE_COLUMNS], train["label"])
    preds = model.predict(test[FEATURE_COLUMNS])
    print(classification_report(test["label"], preds, zero_division=0))

    # The metric that actually matters for a trading model: does a "buy" prediction correspond to
    # a better forward return than a "sell" prediction, on data the model never trained on? A
    # classifier can score well on precision/recall while still having no real trading edge if
    # this ordering doesn't hold.
    test = test.copy()
    test["pred"] = preds
    by_pred = test.groupby("pred")["forward_return"].mean()
    print(f"Mean forward return by prediction (held-out): "
          f"{', '.join(f'{k}={v:+.4f}' for k, v in by_pred.items())}")
    if {"buy", "sell"}.issubset(by_pred.index) and by_pred["buy"] <= by_pred["sell"]:
        print(
            "WARNING: predicted 'buy' rows do not average a higher forward return than predicted "
            "'sell' rows on held-out data — this model has no demonstrated edge. Review the "
            "watchlist, label thresholds, or feature set before trusting it live."
        )


def main() -> int:
    try:
        config = Config()
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 1

    watchlist = config.watchlist
    alpaca = AlpacaClient(
        config.alpaca_base_url, config.alpaca_data_url, config.alpaca_api_key_id, config.alpaca_api_secret_key
    )

    print(f"Fetching {HISTORY_DAYS} days of history for {len(watchlist)} symbols: {', '.join(watchlist)}")
    frames = [f for s in watchlist if (f := build_symbol_dataset(alpaca, s)) is not None]
    if not frames:
        print("No usable data for any watchlist symbol — nothing to train on.", file=sys.stderr)
        return 1

    dataset = pd.concat(frames)
    print(f"\nTotal labeled rows across watchlist: {len(dataset)}")
    print(dataset["label"].value_counts())

    evaluate_time_split(dataset)

    print("\nRefitting on the full dataset for deployment...")
    final_model = GradientBoostingClassifier(random_state=0)
    final_model.fit(dataset[FEATURE_COLUMNS], dataset["label"])

    bundle = {
        "model": final_model,
        "feature_columns": FEATURE_COLUMNS,
        "watchlist": watchlist,
        "label_horizon_days": LABEL_HORIZON_DAYS,
        "buy_threshold": BUY_THRESHOLD,
        "sell_threshold": SELL_THRESHOLD,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_rows": len(dataset),
    }
    joblib.dump(bundle, MODEL_PATH)
    print(f"Saved {MODEL_PATH} ({len(dataset)} training rows, watchlist: {', '.join(watchlist)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
