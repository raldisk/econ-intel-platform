"""
test_psx_transform.py — unit tests for PSX transform signal computations.

Feeds controlled fixture DataFrames through _transform_ticker() and asserts:
  - Output column schema matches DuckDB view schema
  - RSI is in [0, 100] for rows with sufficient history
  - MA crossover signal is one of the three expected strings
  - pct_change is reasonable (no infinity, within bounds)
  - Dead code _ma_signal() is absent from the module

Run: pytest tests/test_psx_transform.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import date, timedelta

import pandas as pd
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipelines.psx.transform import _transform_ticker, _rsi, _volume_zscore, _compute_ma_signal


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int = 100, ticker: str = "BDO.PS") -> pd.DataFrame:
    """
    Synthetic OHLCV DataFrame with n rows.
    Prices follow a simple linear trend with small noise to produce
    both RSI and MA signal variety.
    """
    rng = np.random.default_rng(seed=42)
    base = np.linspace(80.0, 120.0, n)          # uptrend base
    noise = rng.normal(0, 1.5, n)
    close = base + noise
    close = np.clip(close, 1.0, 999.0)

    dates = pd.date_range(
        start=date(2023, 1, 1), periods=n, freq="B"  # business days
    )
    return pd.DataFrame({
        "Date":   dates,
        "Open":   close * 0.99,
        "High":   close * 1.01,
        "Low":    close * 0.98,
        "Close":  close,
        "Volume": rng.integers(100_000, 5_000_000, n).astype(float),
        "ticker": ticker,
    })


# ---------------------------------------------------------------------------
# Column schema
# ---------------------------------------------------------------------------

EXPECTED_COLUMNS = {
    "date", "ticker",
    "open", "high", "low", "close", "volume",
    "pct_change",
    "rsi_14", "ma_20", "ma_50", "ma_signal",
    "volume_zscore",
}


def test_output_columns_match_schema():
    df = _make_ohlcv(100)
    result = _transform_ticker(df)
    assert set(result.columns) == EXPECTED_COLUMNS


def test_column_names_are_lowercase():
    df = _make_ohlcv(100)
    result = _transform_ticker(df)
    for col in result.columns:
        assert col == col.lower(), f"Column not lowercase: {col}"


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

def test_rsi_in_valid_range():
    """RSI must be in [0, 100] for rows with sufficient history (>= 14 bars)."""
    df = _make_ohlcv(100)
    result = _transform_ticker(df)
    rsi_vals = result["rsi_14"].dropna()
    assert len(rsi_vals) > 0, "All RSI values are NaN — insufficient data?"
    assert (rsi_vals >= 0).all(),   f"RSI below 0: {rsi_vals[rsi_vals < 0]}"
    assert (rsi_vals <= 100).all(), f"RSI above 100: {rsi_vals[rsi_vals > 100]}"


def test_rsi_nan_for_early_rows():
    """First 13 rows should have NaN RSI (insufficient history for period=14)."""
    df = _make_ohlcv(100)
    result = _transform_ticker(df)
    early_rsi = result["rsi_14"].iloc[:13]
    assert early_rsi.isna().all(), "Expected NaN RSI for rows before min_periods"


# ---------------------------------------------------------------------------
# MA signal
# ---------------------------------------------------------------------------

VALID_SIGNALS = {"bullish", "bearish", "neutral"}


def test_ma_signal_values():
    """ma_signal must only contain the three expected string values."""
    df = _make_ohlcv(100)
    result = _transform_ticker(df)
    unique = set(result["ma_signal"].dropna().unique())
    unexpected = unique - VALID_SIGNALS
    assert not unexpected, f"Unexpected ma_signal values: {unexpected}"


def test_ma_signal_bullish_when_ma20_above_ma50():
    """On an uptrend fixture, late rows should have ma_20 > ma_50 → bullish."""
    df = _make_ohlcv(120)   # extra rows so MA50 has full history
    result = _transform_ticker(df)
    late = result.dropna(subset=["ma_20", "ma_50"]).tail(20)
    bullish_rows = late[late["ma_20"] > late["ma_50"]]
    # Uptrend fixture should have at least some bullish rows
    assert len(bullish_rows) > 0, "Expected bullish rows in uptrend fixture"
    assert (bullish_rows["ma_signal"] == "bullish").all()


# ---------------------------------------------------------------------------
# pct_change
# ---------------------------------------------------------------------------

def test_pct_change_no_infinity():
    df = _make_ohlcv(100)
    result = _transform_ticker(df)
    pct = result["pct_change"].dropna()
    assert not np.isinf(pct).any(), "pct_change contains infinity"


def test_pct_change_first_row_is_nan():
    """First row has no prior close — pct_change must be NaN."""
    df = _make_ohlcv(100)
    result = _transform_ticker(df)
    assert pd.isna(result["pct_change"].iloc[0])


# ---------------------------------------------------------------------------
# volume_zscore
# ---------------------------------------------------------------------------

def test_volume_zscore_no_infinity():
    df = _make_ohlcv(100)
    result = _transform_ticker(df)
    zs = result["volume_zscore"].dropna()
    assert not np.isinf(zs).any(), "volume_zscore contains infinity"


def test_volume_zscore_nan_for_early_rows():
    """First 19 rows (< window=20) should have NaN volume_zscore."""
    df = _make_ohlcv(100)
    result = _transform_ticker(df)
    early = result["volume_zscore"].iloc[:19]
    assert early.isna().all(), "Expected NaN volume_zscore before rolling window fills"


# ---------------------------------------------------------------------------
# Dead code guard
# ---------------------------------------------------------------------------

def test_ma_signal_dead_code_removed():
    """
    _ma_signal() was a broken dead-code function in the original transform.py.
    It must not exist in the fixed version.
    """
    import pipelines.psx.transform as tx_module
    assert not hasattr(tx_module, "_ma_signal"), (
        "_ma_signal() dead code function is still present — delete it."
    )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_transform_handles_single_ticker_minimal_rows():
    """Transform must not crash on a DataFrame with just enough rows for MA50."""
    df = _make_ohlcv(51)    # exactly one row with full MA50 history
    result = _transform_ticker(df)
    assert len(result) == 51


def test_transform_preserves_ticker_column():
    ticker = "BPI.PS"
    df = _make_ohlcv(60, ticker=ticker)
    result = _transform_ticker(df)
    assert (result["ticker"] == ticker).all()


def test_output_sorted_by_date():
    """Output must be sorted ascending by date."""
    df = _make_ohlcv(80)
    # Shuffle input to ensure transform enforces sort
    df = df.sample(frac=1, random_state=7).reset_index(drop=True)
    result = _transform_ticker(df)
    assert result["date"].is_monotonic_increasing, "Output is not sorted by date"