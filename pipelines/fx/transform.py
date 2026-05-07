"""
FX transform — deduplicate raw FX JSON and write clean parquets.

Input:
  data/raw/fx/fx_daily.json   — daily + monthly USD/PHP records
  data/raw/fx/fx_cross.json   — cross rate records

Output:
  data/processed/fx/fx_rates.parquet
    Columns: rate_date (datetime64), currency_pair (str), rate (float64), source (str)
    Contains both USD/PHP daily/monthly and cross rates (base_currency/PHP pairs).

Deduplication:
  Multiple sources may provide the same (rate_date, currency_pair) —
  e.g. bsp_rerb and bsp_table12 both cover recent daily rates.
  Keep the row with the most specific source in priority order:
    bsp_rerb > bsp_table12 > frankfurter

Raises:
  FileNotFoundError — if raw JSON not found (extract not run)
  ValueError        — if deduplicated DataFrame is empty
"""

from __future__ import annotations

import json
import logging

import pandas as pd

import config as cfg
from db.init import PARQUET_MAP

logger = logging.getLogger(__name__)

# Source priority: lower number = preferred when deduplicating same (date, pair)
_SOURCE_PRIORITY = {
    "bsp_rerb":     1,
    "bsp_table12":  2,
    "frankfurter":  3,
    "bsp_table13":  1,  # sole source for cross rates — no dedup needed
}


def transform() -> None:
    """
    Load raw FX JSON → clean, deduplicate → write fx_rates.parquet.

    Schema:
        rate_date       datetime64[ns]  — date of observation
        currency_pair   object          — 'USD/PHP', 'EUR/PHP', etc.
        rate            float64         — exchange rate
        source          object          — ingestion source label
    """
    daily_path = cfg.FX_RAW_DIR / "fx_daily.json"
    cross_path = cfg.FX_RAW_DIR / "fx_cross.json"

    if not daily_path.exists():
        raise FileNotFoundError(
            f"FX raw file not found: {daily_path} — run extract() first."
        )

    # Load daily/monthly USD/PHP records
    daily_raw = json.loads(daily_path.read_text(encoding="utf-8"))
    df_daily = pd.DataFrame(daily_raw)

    # Load cross rate records (EUR/PHP, JPY/PHP, etc.)
    cross_raw: list[dict] = []
    if cross_path.exists():
        cross_raw = json.loads(cross_path.read_text(encoding="utf-8"))

    if cross_raw:
        df_cross = pd.DataFrame(cross_raw)
        # Normalise column names to match df_daily schema
        df_cross = df_cross.rename(columns={
            "base_currency": "_base_currency",
            "php_rate": "rate",
        })
        df_cross["currency_pair"] = df_cross["_base_currency"] + "/PHP"
        df_cross = df_cross.drop(columns=["_base_currency"])
        df = pd.concat([df_daily, df_cross], ignore_index=True)
    else:
        df = df_daily.copy()

    if df.empty:
        raise ValueError("FX transform: no records to process.")

    # Type coercion
    df["rate_date"] = pd.to_datetime(df["rate_date"])
    df["rate"]      = df["rate"].astype(float)
    df["currency_pair"] = df["currency_pair"].astype(str)
    df["source"]    = df["source"].astype(str)

    # Deduplication: for same (rate_date, currency_pair), keep highest-priority source.
    # Priority value: lower = better. Default 99 for unknown sources.
    df["_priority"] = df["source"].map(_SOURCE_PRIORITY).fillna(99)
    df = (
        df.sort_values("_priority")
          .drop_duplicates(subset=["rate_date", "currency_pair"], keep="first")
          .drop(columns=["_priority"])
    )

    # Drop rows with null rates
    df = df[df["rate"].notna() & (df["rate"] > 0)]

    if df.empty:
        raise ValueError("FX transform: all records filtered out after deduplication.")

    df = df.sort_values(["currency_pair", "rate_date"]).reset_index(drop=True)

    out_path = PARQUET_MAP["FX_PARQUET"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)

    usd = df[df["currency_pair"] == "USD/PHP"]
    cross = df[df["currency_pair"] != "USD/PHP"]

    logger.info(
        "FX transform complete: %d total rows "
        "(USD/PHP: %d [%s → %s], cross pairs: %d) → %s",
        len(df),
        len(usd),
        usd["rate_date"].min().date() if not usd.empty else "n/a",
        usd["rate_date"].max().date() if not usd.empty else "n/a",
        len(cross),
        out_path,
    )