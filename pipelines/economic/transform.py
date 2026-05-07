"""
Economic transform — computes CPI, GDP, remittance, and dashboard marts
from raw indicators.json and remittances.json.

Ports four dbt mart models to pandas computation:
  cpi_trend        — monthly CPI index + inflation + MoM change (cpi_trend.sql)
  gdp_tracker      — annual GDP series + YoY growth (gdp_trend.sql)
  remittance_trend — annual OFW remittance + YoY growth + 3yr avg (remittance_trend.sql)
  economic_dashboard — wide annual join of GDP × CPI × remittances (economic_dashboard.sql)

Input:
  data/raw/economic/indicators.json   — list of EconomicIndicator dicts
  data/raw/economic/remittances.json  — list of OFWRemittance dicts

Output:
  data/processed/economic/cpi_trend.parquet
  data/processed/economic/gdp_tracker.parquet
  data/processed/economic/remittance_trend.parquet
  data/processed/economic/economic_dashboard.parquet

Schema mirrors the original dbt mart column names exactly — downstream
DuckDB views, Streamlit pages, and Dash selectors all reference these names.

Raises:
  FileNotFoundError — if raw JSON not found (extract not run)
  ValueError        — if any output DataFrame is empty after computation
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

import config as cfg

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_indicators() -> pd.DataFrame:
    path: Path = cfg.ECONOMIC_RAW_DIR / "indicators.json"
    if not path.exists():
        raise FileNotFoundError(
            f"indicators.json not found at {path} — run extract() first."
        )
    records = json.loads(path.read_text(encoding="utf-8"))
    df = pd.DataFrame(records)
    df["period_date"] = pd.to_datetime(df["period_date"], errors="coerce")
    df["period_year"]  = df["period_date"].dt.year
    df["period_month"] = df["period_date"].dt.month
    df["series_code"]  = df["series_code"].str.upper().str.strip()
    df["source"]       = df["source"].str.strip()
    df = df[df["value"].notna()]

    def _classify(code: str) -> str:
        if any(x in code for x in ("GDP", "NY.GDP")):
            return "gdp"
        if any(x in code for x in ("CPI", "FP.CPI")):
            return "cpi"
        if any(x in code for x in ("UNEM", "SL.UEM")):
            return "employment"
        return "other"

    df["indicator_type"] = df["series_code"].apply(_classify)
    return df


def _load_remittances() -> pd.DataFrame:
    path: Path = cfg.ECONOMIC_RAW_DIR / "remittances.json"
    if not path.exists():
        raise FileNotFoundError(
            f"remittances.json not found at {path} — run extract() first."
        )
    records = json.loads(path.read_text(encoding="utf-8"))
    df = pd.DataFrame(records)
    df["period_date"] = pd.to_datetime(df["period_date"], errors="coerce")
    df["period_year"]  = df["period_date"].dt.year
    df["period_month"] = df["period_date"].dt.month
    df["period_label"] = df["period_date"].dt.strftime("%Y-%m")
    df["country_destination"] = (
        df["country_destination"].fillna("").str.strip().replace("", "ALL")
    )
    df["remittance_usd_bn"] = (df["remittance_usd"] / 1_000_000_000).round(3)
    df = df[df["remittance_usd"].notna() | df["remittance_pct_gdp"].notna()]
    return df


# ---------------------------------------------------------------------------
# cpi_trend — port of cpi_trend.sql
# ---------------------------------------------------------------------------

def _build_cpi_trend(df: pd.DataFrame) -> pd.DataFrame:
    """
    Merge PSA monthly CPI index + YoY series with World Bank annual CPI.
    Compute MoM absolute change and MoM percent change.
    Mirrors cpi_trend.sql logic exactly.
    """
    psa_index = (
        df[(df["series_code"] == "CPI_ALL_ITEMS") & (df["source"] == "PSA")]
        [["period_date", "period_year", "period_month", "value"]]
        .rename(columns={"value": "cpi_index"})
    )
    psa_yoy = (
        df[(df["series_code"] == "CPI_YOY_CHANGE") & (df["source"] == "PSA")]
        [["period_date", "period_year", "period_month", "value"]]
        .rename(columns={"value": "inflation_pct"})
    )
    wb_annual = (
        df[(df["series_code"] == "FP.CPI.TOTL.ZG") & (df["source"] == "WORLD_BANK")]
        [["period_year", "value"]]
        .rename(columns={"value": "inflation_pct_wb"})
    )

    # Full outer join on period_date (mirrors dbt FULL OUTER JOIN)
    monthly = pd.merge(
        psa_index, psa_yoy,
        on=["period_date", "period_year", "period_month"],
        how="outer",
    )

    # Left join World Bank annual inflation
    monthly = monthly.merge(wb_annual, on="period_year", how="left")

    monthly = monthly[monthly["period_date"].notna()].sort_values("period_date")
    monthly["period_label"] = monthly["period_date"].dt.strftime("%Y-%m")
    monthly["prev_cpi_index"] = monthly["cpi_index"].shift(1)
    monthly["cpi_mom_change"] = monthly["cpi_index"] - monthly["prev_cpi_index"]
    monthly["cpi_mom_pct"] = (
        monthly["cpi_mom_change"] / monthly["prev_cpi_index"].replace(0, None) * 100
    ).round(2)

    return monthly[[
        "period_date", "period_year", "period_month",
        "cpi_index", "inflation_pct", "inflation_pct_wb",
        "period_label", "prev_cpi_index", "cpi_mom_change", "cpi_mom_pct",
    ]]


# ---------------------------------------------------------------------------
# gdp_tracker — port of gdp_trend.sql
# ---------------------------------------------------------------------------

def _build_gdp_tracker(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build annual GDP series from World Bank indicators.
    Computes gdp_usd_bn, YoY absolute change, and YoY pct.
    Mirrors gdp_trend.sql logic.
    """
    base = df[(df["indicator_type"] == "gdp") & (df["source"] == "WORLD_BANK")]

    gdp_current = (
        base[base["series_code"] == "NY.GDP.MKTP.CD"]
        [["period_year", "period_date", "value"]]
        .rename(columns={"value": "gdp_usd"})
    )
    gdp_growth = (
        base[base["series_code"] == "NY.GDP.MKTP.KD.ZG"]
        [["period_year", "value"]]
        .rename(columns={"value": "gdp_growth_pct"})
    )
    gdp_per_capita = (
        base[base["series_code"] == "NY.GDP.PCAP.CD"]
        [["period_year", "value"]]
        .rename(columns={"value": "gdp_per_capita_usd"})
    )

    joined = (
        gdp_current
        .merge(gdp_growth, on="period_year", how="left")
        .merge(gdp_per_capita, on="period_year", how="left")
        .sort_values("period_year")
    )

    joined["gdp_usd_bn"] = (joined["gdp_usd"] / 1_000_000_000).round(3)
    joined["prev_gdp_usd"] = joined["gdp_usd"].shift(1)
    joined["gdp_yoy_change_usd"] = joined["gdp_usd"] - joined["prev_gdp_usd"]
    joined["gdp_yoy_pct_computed"] = (
        joined["gdp_yoy_change_usd"] / joined["prev_gdp_usd"].replace(0, None) * 100
    ).round(2)

    return joined[[
        "period_year", "period_date",
        "gdp_usd", "gdp_usd_bn", "gdp_growth_pct", "gdp_per_capita_usd",
        "prev_gdp_usd", "gdp_yoy_change_usd", "gdp_yoy_pct_computed",
    ]]


# ---------------------------------------------------------------------------
# remittance_trend — port of remittance_trend.sql
# ---------------------------------------------------------------------------

def _build_remittance_trend(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build annual OFW remittance trend with YoY change and 3-year rolling average.
    Filters to country_destination='ALL', frequency='ANNUAL'.
    Mirrors remittance_trend.sql logic.
    """
    annual = df[
        (df["country_destination"] == "ALL") &
        (df["frequency"].str.upper() == "ANNUAL")
    ].sort_values("period_year").copy()

    annual["prev_remittance_usd"] = annual["remittance_usd"].shift(1)
    annual["remittance_yoy_change_usd"] = (
        annual["remittance_usd"] - annual["prev_remittance_usd"]
    )
    annual["remittance_yoy_pct"] = (
        annual["remittance_yoy_change_usd"]
        / annual["prev_remittance_usd"].replace(0, None) * 100
    ).round(2)

    # 3-year rolling average in USD billions (smooths election-year spikes)
    annual["remittance_3yr_avg_bn"] = (
        annual["remittance_usd"]
        .rolling(window=3, min_periods=1)
        .mean() / 1_000_000_000
    ).round(3)

    return annual[[
        "period_year", "period_date", "source",
        "remittance_usd", "remittance_usd_bn", "remittance_pct_gdp",
        "ofw_count", "period_label",
        "prev_remittance_usd", "remittance_3yr_avg_bn",
        "remittance_yoy_change_usd", "remittance_yoy_pct",
    ]]


# ---------------------------------------------------------------------------
# economic_dashboard — port of economic_dashboard.sql
# ---------------------------------------------------------------------------

def _build_economic_dashboard(
    cpi: pd.DataFrame,
    gdp: pd.DataFrame,
    remittance: pd.DataFrame,
) -> pd.DataFrame:
    """
    Wide annual dashboard table joining GDP × CPI × remittances.
    Primary source for Streamlit summary cards.
    Mirrors economic_dashboard.sql logic (FULL OUTER JOIN on period_year).
    """
    cpi_annual = (
        cpi[cpi["cpi_index"].notna()]
        .groupby("period_year", as_index=False)
        .agg(
            avg_cpi_index=("cpi_index", "mean"),
            avg_inflation_pct=("inflation_pct", "mean"),
        )
    )
    cpi_annual["avg_cpi_index"]    = cpi_annual["avg_cpi_index"].round(2)
    cpi_annual["avg_inflation_pct"] = cpi_annual["avg_inflation_pct"].round(2)

    gdp_slim = gdp[[
        "period_year", "gdp_usd_bn", "gdp_growth_pct", "gdp_per_capita_usd",
    ]]
    rem_slim = remittance[[
        "period_year", "remittance_usd_bn", "remittance_pct_gdp", "remittance_yoy_pct",
    ]]

    dash = (
        gdp_slim
        .merge(cpi_annual, on="period_year", how="outer")
        .merge(rem_slim, on="period_year", how="outer")
    )
    dash = dash[dash["period_year"].notna()].sort_values("period_year")

    dash["remit_to_gdp_pct_computed"] = (
        dash["remittance_usd_bn"] / dash["gdp_usd_bn"].replace(0, None) * 100
    ).round(2)

    return dash[[
        "period_year",
        "gdp_usd_bn", "gdp_growth_pct", "gdp_per_capita_usd",
        "avg_cpi_index", "avg_inflation_pct",
        "remittance_usd_bn", "remittance_pct_gdp", "remittance_yoy_pct",
        "remit_to_gdp_pct_computed",
    ]]


# ---------------------------------------------------------------------------
# transform()
# ---------------------------------------------------------------------------

def transform() -> None:
    """
    Compute all four economic mart DataFrames and write to processed parquets.

    Raises FileNotFoundError if raw JSON is absent (extract not run).
    Raises ValueError if any output DataFrame is empty.
    """
    logger.info("Economic transform: loading raw JSON...")
    indicators  = _load_indicators()
    remittances = _load_remittances()

    logger.info(
        "Raw loaded: %d indicator records, %d remittance records",
        len(indicators), len(remittances),
    )

    cpi_df  = _build_cpi_trend(indicators)
    gdp_df  = _build_gdp_tracker(indicators)
    rem_df  = _build_remittance_trend(remittances)
    dash_df = _build_economic_dashboard(cpi_df, gdp_df, rem_df)

    outputs = {
        "cpi_trend":          (cpi_df,  cfg.ECONOMIC_PROCESSED_DIR / "cpi_trend.parquet"),
        "gdp_tracker":        (gdp_df,  cfg.ECONOMIC_PROCESSED_DIR / "gdp_tracker.parquet"),
        "remittance_trend":   (rem_df,  cfg.ECONOMIC_PROCESSED_DIR / "remittance_trend.parquet"),
        "economic_dashboard": (dash_df, cfg.ECONOMIC_PROCESSED_DIR / "economic_dashboard.parquet"),
    }

    cfg.ECONOMIC_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    for name, (df, path) in outputs.items():
        if df.empty:
            raise ValueError(
                f"Economic transform produced empty DataFrame for '{name}'. "
                f"Check that extract() wrote valid data to {cfg.ECONOMIC_RAW_DIR}."
            )
        df.to_parquet(path, index=False)
        logger.info("Written: %s (%d rows → %s)", name, len(df), path)

    logger.info(
        "Economic transform complete: cpi=%d rows | gdp=%d rows | "
        "remittance=%d rows | dashboard=%d rows",
        len(cpi_df), len(gdp_df), len(rem_df), len(dash_df),
    )
