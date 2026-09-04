"""Technical-indicator feature engineering, shared by train_model.py (offline, on historical
bars) and ml_decision.py (live, on the same kind of bars fetched each cycle). Keeping both paths
through this one module is what guarantees the live feature vector is built exactly the way the
model was trained on — a live/train feature mismatch is the single easiest way to silently make
a trained model meaningless.
"""
from __future__ import annotations

import pandas as pd

# How many trailing bars each feature needs before its value is meaningful. The longest lookback
# (SMA_50) sets how much history must be fetched before the first usable row exists.
MIN_BARS_REQUIRED = 60

FEATURE_COLUMNS = [
    "sma10_ratio", "sma20_ratio", "sma50_ratio",
    "ema12_ratio", "ema26_ratio",
    "macd", "macd_signal", "macd_hist",
    "rsi14",
    "bb_position", "bb_width",
    "volatility20",
    "momentum5", "momentum10", "momentum20",
    "volume_ratio",
    "is_crypto",
]


def bars_to_frame(bars: list[dict]) -> pd.DataFrame:
    """Alpaca's raw bar dicts (o/h/l/c/v/t/...) -> a DataFrame indexed by timestamp, oldest first,
    with the columns the rest of this module expects."""
    if not bars:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(bars)
    df["t"] = pd.to_datetime(df["t"])
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    df = df.set_index("t")[["open", "high", "low", "close", "volume"]].sort_index()
    return df


def compute_indicators(df: pd.DataFrame, is_crypto_symbol: bool) -> pd.DataFrame:
    """Given a bars DataFrame (oldest first, columns open/high/low/close/volume), return a new
    DataFrame with one row per input row and FEATURE_COLUMNS as columns. Rows before
    MIN_BARS_REQUIRED history exists are NaN and should be dropped by the caller — returning them
    (rather than trimming here) keeps this function a pure transform, easy to test in isolation.

    Ratios (price / moving average - 1) are used instead of raw price levels throughout so a
    single model trained across symbols spanning $30 stocks to $70,000 Bitcoin sees comparable
    feature scales rather than the model implicitly re-learning each symbol's price magnitude.
    """
    close = df["close"]
    volume = df["volume"]

    sma10 = close.rolling(10).mean()
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()

    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9, adjust=False).mean()

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    # A perfectly flat 14-bar stretch (loss == 0) is a real, if rare, market state — not a
    # divide-by-zero bug — so it's mapped to the maximum RSI value directly rather than left NaN.
    rs = gain / loss.replace(0, pd.NA)
    rsi14 = (100 - (100 / (1 + rs))).fillna(100)

    bb_mid = sma20
    bb_std = close.rolling(20).std()
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    bb_range = (bb_upper - bb_lower).replace(0, pd.NA)
    bb_position = ((close - bb_lower) / bb_range).fillna(0.5)
    bb_width = (bb_range / bb_mid).fillna(0)

    daily_return = close.pct_change()
    volatility20 = daily_return.rolling(20).std()

    avg_volume20 = volume.rolling(20).mean()

    out = pd.DataFrame(index=df.index)
    out["sma10_ratio"] = close / sma10 - 1
    out["sma20_ratio"] = close / sma20 - 1
    out["sma50_ratio"] = close / sma50 - 1
    out["ema12_ratio"] = close / ema12 - 1
    out["ema26_ratio"] = close / ema26 - 1
    out["macd"] = macd
    out["macd_signal"] = macd_signal
    out["macd_hist"] = macd - macd_signal
    out["rsi14"] = rsi14
    out["bb_position"] = bb_position
    out["bb_width"] = bb_width
    out["volatility20"] = volatility20
    out["momentum5"] = close / close.shift(5) - 1
    out["momentum10"] = close / close.shift(10) - 1
    out["momentum20"] = close / close.shift(20) - 1
    out["volume_ratio"] = (volume / avg_volume20.replace(0, pd.NA)).fillna(1.0)
    out["is_crypto"] = 1.0 if is_crypto_symbol else 0.0
    return out[FEATURE_COLUMNS]
