"""
Prices transform — STL decomposition of commodity retail prices.

Input:
  data/raw/prices/psa_prices.json   — commodity retail price observations
  data/raw/prices/doe_fuel.json     — weekly fuel prices

Output:
  data/processed/prices/commodity_prices.parquet
    Columns: price_date (datetime64), commodity_slug (str), commodity (str),
             retail_price_php (float), unit (str), region (str), source (str)
    Monthly average of bi-monthly PSA observations + fuel prices converted
    to monthly average.

  data/processed/prices/food_price_decomposition.parquet
    Columns: period (datetime64), commodity_slug (str),
             observed (float), trend (float), seasonal (float), residual (float)
    STL decomposition per commodity — monthly, national average only.
    Only commodities with sufficient history (>=24 monthly observations) are decomposed.

STL parameters (from PH-Food-Price-Decomposition/notebooks/05_stl_decomposition.ipynb):
  period=12   — seasonal period is 12 months
  robust=True — uses bisquare weight function, resistant to outliers
  seasonal=7  — seasonal smoother (odd number required; 7 is statsmodels default)

Raises:
  FileNotFoundError — if psa_prices.json not found (extract not run)
  ValueError        — if both output DataFrames are empty after processing
"""

from __future__ import annotations

import json
import logging
import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.seasonal import STL

import config as cfg
from db.init import PARQUET_MAP

logger = logging.getLogger(__name__)

_STL_MIN_PERIODS = 24  # minimum monthly observations required for STL
_STL_PERIOD      = 12  # seasonal period: 12 months
_STL_SEASONAL    = 7   # seasonal smoother window (must be odd)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def _load_psa() -> pd.DataFrame:
    path = cfg.PRICES_RAW_DIR / "psa_prices.json"
    if not path.exists():
        raise FileNotFoundError(
            f"PSA prices not found: {path} — run extract() first."
        )
    records = json.loads(path.read_text(encoding="utf-8"))
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    df["price_date"] = pd.to_datetime(df["price_date"], errors="coerce")
    df["retail_price_php"] = pd.to_numeric(df["retail_price_php"], errors="coerce")
    return df.dropna(subset=["price_date", "retail_price_php"])


def _load_fuel() -> pd.DataFrame:
    path = cfg.PRICES_RAW_DIR / "doe_fuel.json"
    if not path.exists():
        return pd.DataFrame()
    records = json.loads(path.read_text(encoding="utf-8"))
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    df["price_date"] = pd.to_datetime(df["price_date"], errors="coerce")
    df["price_php"] = pd.to_numeric(df["price_php"], errors="coerce")
    return df.dropna(subset=["price_date", "price_php"])


# ---------------------------------------------------------------------------
# Commodity prices: monthly average from bi-monthly PSA + weekly DOE fuel
# ---------------------------------------------------------------------------

def _build_commodity_prices(df_psa: pd.DataFrame, df_fuel: pd.DataFrame) -> pd.DataFrame:
    """
    Build monthly national average commodity price table.
    PSA observations are bi-monthly (phase 1 + phase 2 per month) → averaged.
    DOE fuel is weekly → monthly average.
    """
    frames: list[pd.DataFrame] = []

    if not df_psa.empty:
        # Monthly average for National observations
        national = df_psa[df_psa["region"].str.upper() == "NATIONAL"].copy()
        if national.empty:
            national = df_psa.copy()

        national["month"] = national["price_date"].dt.to_period("M").dt.to_timestamp()
        monthly = (
            national.groupby(["month", "commodity_slug", "commodity", "unit", "source"])
            .agg(retail_price_php=("retail_price_php", "mean"))
            .reset_index()
            .rename(columns={"month": "price_date"})
        )
        monthly["region"] = "National"
        monthly["retail_price_php"] = monthly["retail_price_php"].round(2)
        frames.append(monthly[[
            "price_date", "commodity_slug", "commodity",
            "retail_price_php", "unit", "region", "source"
        ]])

    if not df_fuel.empty:
        # Monthly average fuel price per fuel type
        national_fuel = df_fuel[df_fuel["region"].str.upper() == "NATIONAL"].copy()
        if national_fuel.empty:
            national_fuel = df_fuel.copy()

        national_fuel["month"] = national_fuel["price_date"].dt.to_period("M").dt.to_timestamp()
        monthly_fuel = (
            national_fuel.groupby(["month", "fuel_type", "source"])
            .agg(price_php=("price_php", "mean"))
            .reset_index()
            .rename(columns={"month": "price_date", "fuel_type": "commodity_slug",
                              "price_php": "retail_price_php"})
        )
        monthly_fuel["commodity"] = monthly_fuel["commodity_slug"].str.replace("_", " ").str.title()
        monthly_fuel["unit"] = monthly_fuel["commodity_slug"].apply(
            lambda x: "litre" if x in ("gasoline", "diesel") else "kg"
        )
        monthly_fuel["region"] = "National"
        monthly_fuel["retail_price_php"] = monthly_fuel["retail_price_php"].round(2)
        frames.append(monthly_fuel[[
            "price_date", "commodity_slug", "commodity",
            "retail_price_php", "unit", "region", "source"
        ]])

    if not frames:
        return pd.DataFrame()

    out = pd.concat(frames, ignore_index=True)
    out = out.sort_values(["commodity_slug", "price_date"]).reset_index(drop=True)
    return out


# ---------------------------------------------------------------------------
# STL decomposition
# ---------------------------------------------------------------------------

def _run_stl(series: pd.Series, commodity_slug: str) -> pd.DataFrame | None:
    """
    Run STL decomposition on a monthly price series.
    Returns DataFrame with (period, observed, trend, seasonal, residual) or None.

    Requires >=24 observations. Missing months are forward-filled before decomposition.
    """
    if len(series) < _STL_MIN_PERIODS:
        logger.debug(
            "STL: skip %s — only %d monthly observations (need %d).",
            commodity_slug, len(series), _STL_MIN_PERIODS,
        )
        return None

    # Fill missing months with forward fill (sparse series from synthetic data will be complete)
    full_idx = pd.date_range(series.index.min(), series.index.max(), freq="MS")
    series = series.reindex(full_idx).ffill().bfill()

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            stl = STL(series, period=_STL_PERIOD, seasonal=_STL_SEASONAL, robust=True)
            result = stl.fit()
    except Exception as exc:
        logger.warning("STL failed for %s: %s", commodity_slug, exc)
        return None

    df = pd.DataFrame({
        "period":       series.index,
        "commodity_slug": commodity_slug,
        "observed":     result.observed.round(4),
        "trend":        result.trend.round(4),
        "seasonal":     result.seasonal.round(4),
        "residual":     result.resid.round(4),
    })
    return df


def _build_stl_decomposition(df_prices: pd.DataFrame) -> pd.DataFrame:
    """
    Run STL decomposition for each commodity slug on National monthly averages.
    Returns food_price_decomposition DataFrame.
    """
    if df_prices.empty:
        return pd.DataFrame()

    national = df_prices[df_prices["region"] == "National"].copy()
    if national.empty:
        return pd.DataFrame()

    # Only PSA commodity slugs (not fuel — fuel STL is less meaningful at monthly grain)
    psa_slugs = [s for s in national["commodity_slug"].unique()
                 if s not in ("gasoline", "diesel", "lpg")]

    decomp_frames: list[pd.DataFrame] = []
    for slug in sorted(psa_slugs):
        slug_df = (
            national[national["commodity_slug"] == slug]
            .set_index("price_date")["retail_price_php"]
            .sort_index()
        )
        result = _run_stl(slug_df, slug)
        if result is not None:
            decomp_frames.append(result)
            logger.debug("STL: %s — %d decomp rows", slug, len(result))

    if not decomp_frames:
        logger.warning("STL decomposition produced no results — check input data.")
        return pd.DataFrame()

    out = pd.concat(decomp_frames, ignore_index=True)
    out = out.sort_values(["commodity_slug", "period"]).reset_index(drop=True)
    logger.info("STL decomposition complete: %d rows | %d commodities.",
                len(out), out["commodity_slug"].nunique())
    return out


# ---------------------------------------------------------------------------
# transform()
# ---------------------------------------------------------------------------

def transform() -> None:
    """
    Build commodity_prices and food_price_decomposition parquets.

    commodity_prices:         monthly national avg per commodity + fuel
    food_price_decomposition: STL trend/seasonal/residual per commodity-month
    """
    cfg.PRICES_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    df_psa  = _load_psa()
    df_fuel = _load_fuel()

    if df_psa.empty:
        raise ValueError("Prices transform: PSA data is empty — run extract() first.")

    logger.info("Prices transform: building commodity prices from %d PSA + %d fuel records.",
                len(df_psa), len(df_fuel))

    prices  = _build_commodity_prices(df_psa, df_fuel)
    decomp  = _build_stl_decomposition(prices)

    if prices.empty and decomp.empty:
        raise ValueError("Prices transform: both output DataFrames are empty.")

    def _write(df: pd.DataFrame, key: str, label: str) -> None:
        if df.empty:
            logger.warning("Prices transform: %s is empty — skipping.", label)
            return
        path = PARQUET_MAP[key]
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)
        logger.info("Prices transform: %s → %d rows → %s", label, len(df), path)

    _write(prices, "COMMODITY_PARQUET", "commodity_prices")
    _write(decomp, "FOOD_PARQUET",      "food_price_decomposition")
    logger.info("Prices transform complete.")