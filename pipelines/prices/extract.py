"""
Prices extract — loads PSA commodity retail prices and DOE fuel price data.

Sources:
  PSA Price Situationer — bi-monthly retail prices for 12 key commodities
    National + regional, ₱/kg or ₱/litre
    Files: psa_prices_<YYYY>.csv or psa_prices_sample.csv
    URL:   https://psa.gov.ph/statistics/price-situationer (manual download)

  DOE Weekly Oil Monitor — weekly pump prices for gasoline, diesel, LPG
    Files: doe_fuel_prices.csv
    URL:   https://www.doe.gov.ph/weekly-retail-pump-prices (manual download)

Fallback:
  If no source CSVs are found, extract() generates synthetic data using the
  same generator logic from PH-Food-Price-Decomposition/scripts/.
  Synthetic data is tagged source='SYNTHETIC_FALLBACK'.
  The fallback is seeded (reproducible) and covers 2000-01-01 through today.

Output:
  data/raw/prices/psa_prices.json   — list of commodity price dicts
  data/raw/prices/doe_fuel.json     — list of fuel price dicts

Interface contract:
    extract() -> None
    Always succeeds (fallback guarantees output). Logs clearly if fallback used.
    Uses lib/sources/ttl_cache for on-demand refresh gating.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import config as cfg
from lib.sources.ttl_cache import get_or_fetch, is_fresh

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Commodity registry (from PH-Food-Price-Decomposition/scripts/scrape_psa_prices.py)
# ---------------------------------------------------------------------------

_COMMODITIES = [
    ("rice_wellmilled", "Well-milled rice",  "kg"),
    ("rice_regular",    "Regular milled rice","kg"),
    ("pork_lean",       "Lean pork",          "kg"),
    ("beef_lean",       "Lean beef",          "kg"),
    ("fish_galunggong", "Galunggong",          "kg"),
    ("fish_tilapia",    "Tilapia",             "kg"),
    ("cooking_oil",     "Cooking oil",        "liter"),
    ("onion_white",     "White onion",        "kg"),
    ("onion_red",       "Red onion",          "kg"),
    ("tomato",          "Tomato",             "kg"),
    ("cabbage",         "Cabbage",            "kg"),
    ("eggplant",        "Eggplant",           "kg"),
]

_PRICE_ANCHORS: dict[str, dict[int, float]] = {
    "rice_wellmilled": {2000:18,2005:21,2010:28,2015:38,2019:37,2020:40,2022:48,2024:54},
    "rice_regular":    {2000:16,2005:19,2010:25,2015:34,2019:33,2020:36,2022:44,2024:49},
    "pork_lean":       {2000:95,2005:110,2010:145,2015:185,2019:200,2020:250,2022:280,2024:320},
    "beef_lean":       {2000:120,2005:145,2010:200,2015:260,2019:290,2020:310,2022:370,2024:410},
    "fish_galunggong": {2000:55,2005:70,2010:95,2015:130,2019:150,2020:170,2022:200,2024:230},
    "fish_tilapia":    {2000:45,2005:60,2010:85,2015:110,2019:130,2020:145,2022:170,2024:195},
    "cooking_oil":     {2000:38,2005:42,2010:55,2015:60,2019:65,2020:72,2022:110,2024:90},
    "onion_white":     {2000:35,2005:40,2010:50,2015:55,2019:60,2020:65,2022:80,2023:350,2024:95},
    "onion_red":       {2000:30,2005:35,2010:45,2015:50,2019:55,2020:60,2022:75,2023:300,2024:90},
    "tomato":          {2000:28,2005:35,2010:45,2015:55,2019:60,2020:68,2022:80,2024:90},
    "cabbage":         {2000:25,2005:32,2010:42,2015:50,2019:55,2020:60,2022:70,2024:78},
    "eggplant":        {2000:22,2005:30,2010:40,2015:48,2019:53,2020:58,2022:65,2024:72},
}

_FUEL_ANCHORS: dict[str, dict[int, float]] = {
    "gasoline": {2010:46,2012:55,2014:58,2016:40,2018:58,2020:40,2022:85,2023:65,2024:62},
    "diesel":   {2010:38,2012:47,2014:49,2016:32,2018:48,2020:33,2022:78,2023:58,2024:57},
    "lpg":      {2010:450,2012:550,2014:600,2016:480,2018:600,2020:520,2022:850,2023:750,2024:720},
}

_SEASONAL_FOOD = {
    1:1.08, 2:1.06, 3:1.02, 4:0.98, 5:0.96, 6:0.97,
    7:1.01, 8:1.07, 9:1.09, 10:1.03, 11:0.97, 12:0.94,
}
_SEASONAL_FUEL = {
    1:1.03,2:1.01,3:0.99,4:0.98,5:0.97,6:0.98,
    7:1.00,8:1.01,9:1.02,10:1.01,11:1.00,12:1.02,
}


# ---------------------------------------------------------------------------
# Interpolation helpers
# ---------------------------------------------------------------------------

def _interpolate(anchors: dict[int, float], year: int) -> float:
    years = sorted(anchors.keys())
    if year <= years[0]:
        return float(anchors[years[0]])
    if year >= years[-1]:
        return float(anchors[years[-1]])
    for i in range(len(years) - 1):
        if years[i] <= year <= years[i + 1]:
            t = (year - years[i]) / (years[i + 1] - years[i])
            return anchors[years[i]] * (1 - t) + anchors[years[i + 1]] * t
    return float(list(anchors.values())[-1])


# ---------------------------------------------------------------------------
# CSV loaders
# ---------------------------------------------------------------------------

_PSA_REQUIRED = {"price_date", "commodity_slug", "retail_price_php"}
_FUEL_REQUIRED = {"price_date", "fuel_type", "price_php"}


def _load_psa_csvs() -> list[dict]:
    """Scan cfg.PRICES_RAW_DIR for psa_prices*.csv files."""
    files = sorted(cfg.PRICES_RAW_DIR.glob("psa_prices*.csv"))
    if not files:
        return []

    frames: list[pd.DataFrame] = []
    for path in files:
        try:
            df = pd.read_csv(path)
            df.columns = [c.strip().lower() for c in df.columns]
            if _PSA_REQUIRED - set(df.columns):
                logger.warning("PSA CSV %s missing required columns — skip.", path.name)
                continue
            df["source"] = df.get("source", pd.Series("PSA_SITUATIONER", index=df.index))
            frames.append(df)
            logger.info("Prices: loaded %s — %d rows", path.name, len(df))
        except Exception as exc:
            logger.warning("Prices: failed to read %s — %s", path.name, exc)

    if not frames:
        return []

    combined = pd.concat(frames, ignore_index=True)
    keep = ["price_date", "commodity_slug", "retail_price_php",
            "unit", "region", "source"]
    keep = [c for c in keep if c in combined.columns]
    return combined[keep].drop_duplicates().to_dict(orient="records")


def _load_fuel_csvs() -> list[dict]:
    """Scan cfg.PRICES_RAW_DIR for doe_fuel*.csv files."""
    files = sorted(cfg.PRICES_RAW_DIR.glob("doe_fuel*.csv"))
    if not files:
        return []

    frames: list[pd.DataFrame] = []
    for path in files:
        try:
            df = pd.read_csv(path)
            df.columns = [c.strip().lower() for c in df.columns]
            if _FUEL_REQUIRED - set(df.columns):
                continue
            frames.append(df)
            logger.info("Fuel: loaded %s — %d rows", path.name, len(df))
        except Exception as exc:
            logger.warning("Fuel: failed to read %s — %s", path.name, exc)

    if not frames:
        return []

    combined = pd.concat(frames, ignore_index=True)
    keep = ["price_date", "fuel_type", "price_php", "region", "source"]
    keep = [c for c in keep if c in combined.columns]
    return combined[keep].drop_duplicates().to_dict(orient="records")


# ---------------------------------------------------------------------------
# Synthetic fallback generators
# ---------------------------------------------------------------------------

def _generate_psa_synthetic() -> list[dict]:
    """
    Generate realistic bi-monthly PSA price data from 2000-01-01 → today.
    Ported from PH-Food-Price-Decomposition/scripts/scrape_psa_prices.py.
    """
    rng = np.random.default_rng(42)
    rows: list[dict] = []
    dates = pd.date_range("2000-01-01", date.today().isoformat(), freq="MS")

    for dt in dates:
        for phase in (1, 2):
            for slug, display, unit in _COMMODITIES:
                base = _interpolate(_PRICE_ANCHORS[slug], dt.year)
                seasonal = _SEASONAL_FOOD.get(dt.month, 1.0)
                price = max(5.0, base * seasonal * float(rng.normal(1.0, 0.025)))
                # Phase 2 has slightly different price from phase 1
                if phase == 2:
                    price = max(5.0, price * float(rng.normal(1.0, 0.015)))
                rows.append({
                    "price_date":       dt.date().isoformat(),
                    "phase":            phase,
                    "commodity_slug":   slug,
                    "commodity":        display,
                    "retail_price_php": round(price, 2),
                    "unit":             unit,
                    "region":           "National",
                    "source":           "SYNTHETIC_FALLBACK",
                })

    logger.warning(
        "Prices extract: no PSA CSVs found — using SYNTHETIC_FALLBACK "
        "(%d commodity-month observations). Place psa_prices_YYYY.csv in %s.",
        len(rows), cfg.PRICES_RAW_DIR,
    )
    return rows


def _generate_fuel_synthetic() -> list[dict]:
    """
    Generate weekly DOE fuel prices from 2010-01-01 → today.
    Ported from PH-Food-Price-Decomposition/scripts/scrape_doe_fuel.py.
    """
    rng = np.random.default_rng(43)
    rows: list[dict] = []
    dates = pd.date_range("2010-01-01", date.today().isoformat(), freq="W-MON")

    for dt in dates:
        for fuel in ("gasoline", "diesel", "lpg"):
            base = _interpolate(_FUEL_ANCHORS[fuel], dt.year)
            seasonal = _SEASONAL_FUEL.get(dt.month, 1.0)
            price = max(1.0, base * seasonal * float(rng.normal(1.0, 0.02)))
            rows.append({
                "price_date": dt.date().isoformat(),
                "fuel_type":  fuel,
                "price_php":  round(price, 2),
                "region":     "National",
                "source":     "SYNTHETIC_FALLBACK",
            })

    logger.warning(
        "Prices extract: no DOE fuel CSVs found — using SYNTHETIC_FALLBACK "
        "(%d weekly fuel observations). Place doe_fuel_prices.csv in %s.",
        len(rows), cfg.PRICES_RAW_DIR,
    )
    return rows


# ---------------------------------------------------------------------------
# extract()
# ---------------------------------------------------------------------------

def extract() -> None:
    """
    Load PSA commodity prices and DOE fuel prices, or generate synthetic fallback.

    To use real data:
      - PSA:  Download price situationer CSV from https://psa.gov.ph/statistics/price-situationer
              Rename to psa_prices_YYYY.csv. Place in data/raw/prices/.
      - DOE:  Download from https://www.doe.gov.ph/weekly-retail-pump-prices
              Rename to doe_fuel_prices.csv. Place in data/raw/prices/.

    Cache:    This pipeline uses TTL cache — re-running within TTL_PRICES seconds
              returns cached results without re-downloading.
    """
    cfg.PRICES_RAW_DIR.mkdir(parents=True, exist_ok=True)

    # Use TTL cache wrapper so on-demand refresh respects TTL_PRICES
    def _fetch_psa() -> list[dict]:
        return _load_psa_csvs() or _generate_psa_synthetic()

    def _fetch_fuel() -> list[dict]:
        return _load_fuel_csvs() or _generate_fuel_synthetic()

    psa_records = get_or_fetch("psa_prices", cfg.TTL_PRICES, _fetch_psa)
    fuel_records = get_or_fetch("doe_fuel",   cfg.TTL_PRICES, _fetch_fuel)

    psa_out  = cfg.PRICES_RAW_DIR / "psa_prices.json"
    fuel_out = cfg.PRICES_RAW_DIR / "doe_fuel.json"

    psa_out.write_text(
        json.dumps(psa_records, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    fuel_out.write_text(
        json.dumps(fuel_records, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    logger.info(
        "Prices extract complete: %d PSA commodity records, %d fuel records.",
        len(psa_records), len(fuel_records),
    )