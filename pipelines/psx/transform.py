"""
PSX transform — normalises raw OHLCV and computes derived signals.

Derived columns added:
  - rsi_14         : RSI (14-period) on Close price
  - ma_20          : 20-day simple moving average of Close
  - ma_50          : 50-day simple moving average of Close
  - ma_signal      : "bullish" | "bearish" | "neutral" (MA20 vs MA50 cross)
  - volume_zscore  : rolling 20-day Z-score of Volume
  - pct_change     : daily Close % change

Input:  data/raw/psx/<ticker>.parquet
Output: data/processed/psx/psx_prices.parquet (all tickers combined)
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

import config as cfg

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Signal computations
# ---------------------------------------------------------------------------

def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    Wilder's RSI.
    Returns a Series of RSI values, NaN for insufficient history.
    """
    delta = series.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs  = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    return rsi.round(2)


def _volume_zscore(series: pd.Series, window: int = 20) -> pd.Series:
    """Rolling Z-score of Volume over *window* days."""
    mean = series.rolling(window).mean()
    std  = series.rolling(window).std()
    return ((series - mean) / std.replace(0, float("nan"))).round(4)


def _compute_ma_signal(df: pd.DataFrame) -> pd.Series:
    """
    Categorical MA crossover signal.
      "bullish"  — MA20 > MA50
      "bearish"  — MA20 < MA50
      "neutral"  — MA20 == MA50 or either is NaN
    """
    signal = pd.Series("neutral", index=df.index, dtype="object")
    signal[df["ma_20"] > df["ma_50"]] = "bullish"
    signal[df["ma_20"] < df["ma_50"]] = "bearish"
    return signal


# ---------------------------------------------------------------------------
# Per-ticker transform
# ---------------------------------------------------------------------------

def _transform_ticker(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"])
    df.sort_values("Date", inplace=True)
    df.reset_index(drop=True, inplace=True)

    close  = df["Close"].astype(float)
    volume = df["Volume"].astype(float)

    df["rsi_14"]        = _rsi(close, cfg.PSX_RSI_PERIOD)
    df["ma_20"]         = close.rolling(cfg.PSX_MA_SHORT).mean().round(4)
    df["ma_50"]         = close.rolling(cfg.PSX_MA_LONG).mean().round(4)
    df["ma_signal"]     = _compute_ma_signal(df)
    df["volume_zscore"] = _volume_zscore(volume, cfg.PSX_VOL_ZSCORE_WINDOW)
    df["pct_change"]    = close.pct_change().mul(100).round(4)

    df.rename(columns={
        "Date":   "date",
        "Open":   "open",
        "High":   "high",
        "Low":    "low",
        "Close":  "close",
        "Volume": "volume",
    }, inplace=True)

    return df[[
        "date", "ticker",
        "open", "high", "low", "close", "volume",
        "pct_change",
        "rsi_14", "ma_20", "ma_50", "ma_signal",
        "volume_zscore",
    ]]


# ---------------------------------------------------------------------------
# Main transform
# ---------------------------------------------------------------------------

def transform() -> None:
    """
    Read all raw ticker parquets, apply signal computations, write combined
    psx_prices.parquet to data/processed/psx/.
    """
    cfg.PSX_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    raw_files = list(cfg.PSX_RAW_DIR.glob("*.parquet"))
    if not raw_files:
        logger.warning("No raw PSX parquets found in %s — nothing to transform.", cfg.PSX_RAW_DIR)
        return

    frames: list[pd.DataFrame] = []
    for path in raw_files:
        try:
            raw = pd.read_parquet(path)
            processed = _transform_ticker(raw)
            frames.append(processed)
            logger.info("Transformed %s: %d rows", path.name, len(processed))
        except Exception as exc:
            logger.error("Transform failed for %s: %s", path.name, exc)

    if not frames:
        logger.error("All ticker transforms failed — no output written.")
        return

    combined = pd.concat(frames, ignore_index=True)
    combined.sort_values(["ticker", "date"], inplace=True)
    combined.reset_index(drop=True, inplace=True)

    out_path = cfg.PSX_PROCESSED_DIR / "psx_prices.parquet"
    combined.to_parquet(out_path, index=False)
    logger.info(
        "PSX transform complete: %d rows | %d tickers → %s",
        len(combined), combined["ticker"].nunique(), out_path,
    )