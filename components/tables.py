"""
components/tables.py — shared styled DataFrame display helpers.

All helpers return a dict ready for st.dataframe(**kwargs) or
st.data_editor(**kwargs). Use like:

    from components.tables import pipeline_runs_table, metric_table
    st.dataframe(**pipeline_runs_table(df))
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def _pct_col(width: str = "small") -> st.column_config.NumberColumn:
    return st.column_config.NumberColumn(format="%.2f%%", width=width)


def _php_col(label: str = "", width: str = "small") -> st.column_config.NumberColumn:
    return st.column_config.NumberColumn(label=label, format="₱%.2f", width=width)


def _usd_bn_col(label: str = "", width: str = "small") -> st.column_config.NumberColumn:
    return st.column_config.NumberColumn(label=label, format="$%.3fB", width=width)


def _date_col(label: str = "", width: str = "medium") -> st.column_config.DateColumn:
    return st.column_config.DateColumn(label=label, format="YYYY-MM-DD", width=width)


# ---------------------------------------------------------------------------
# Pipeline runs table
# ---------------------------------------------------------------------------

def pipeline_runs_table(df: pd.DataFrame) -> dict[str, Any]:
    return dict(
        data=df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "pipeline":      st.column_config.TextColumn("Pipeline", width="small"),
            "status":        st.column_config.TextColumn("Status",   width="small"),
            "rows_affected": st.column_config.NumberColumn("Rows", format="%d", width="small"),
            "error_msg":     st.column_config.TextColumn("Error", width="large"),
            "run_at":        st.column_config.TextColumn("Run at", width="medium"),
        },
    )


# ---------------------------------------------------------------------------
# PSX prices table
# ---------------------------------------------------------------------------

def psx_table(df: pd.DataFrame) -> dict[str, Any]:
    cfg: dict = {}
    if "date" in df.columns:
        cfg["date"] = _date_col("Date")
    for col in ("open", "high", "low", "close"):
        if col in df.columns:
            cfg[col] = st.column_config.NumberColumn(col.title(), format="₱%.2f", width="small")
    if "volume" in df.columns:
        cfg["volume"] = st.column_config.NumberColumn("Volume", format="%,d", width="medium")
    if "rsi_14" in df.columns:
        cfg["rsi_14"] = st.column_config.NumberColumn("RSI-14", format="%.1f", width="small")
    return dict(data=df, use_container_width=True, hide_index=True, column_config=cfg)


# ---------------------------------------------------------------------------
# BSP policy rate table
# ---------------------------------------------------------------------------

def bsp_table(df: pd.DataFrame) -> dict[str, Any]:
    cfg: dict = {}
    if "decision_date" in df.columns:
        cfg["decision_date"] = _date_col("Decision date", width="medium")
    for col in ("overnight_rp", "overnight_srp"):
        if col in df.columns:
            cfg[col] = st.column_config.NumberColumn(col.replace("_", " ").title(),
                                                     format="%.2f%%", width="small")
    if "direction" in df.columns:
        cfg["direction"] = st.column_config.TextColumn("Direction", width="small")
    return dict(data=df, use_container_width=True, hide_index=True, column_config=cfg)


# ---------------------------------------------------------------------------
# FX rates table
# ---------------------------------------------------------------------------

def fx_table(df: pd.DataFrame) -> dict[str, Any]:
    cfg: dict = {}
    if "rate_date" in df.columns:
        cfg["rate_date"] = _date_col("Date")
    if "rate" in df.columns:
        cfg["rate"] = st.column_config.NumberColumn("Rate", format="%.4f", width="small")
    if "currency_pair" in df.columns:
        cfg["currency_pair"] = st.column_config.TextColumn("Pair", width="small")
    return dict(data=df, use_container_width=True, hide_index=True, column_config=cfg)


# ---------------------------------------------------------------------------
# Commodity prices table
# ---------------------------------------------------------------------------

def prices_table(df: pd.DataFrame) -> dict[str, Any]:
    cfg: dict = {}
    if "price_date" in df.columns:
        cfg["price_date"] = _date_col("Date")
    if "commodity" in df.columns:
        cfg["commodity"] = st.column_config.TextColumn("Commodity", width="medium")
    if "retail_price_php" in df.columns:
        cfg["retail_price_php"] = _php_col("Price (₱/kg)", width="small")
    if "yoy_change_pct" in df.columns:
        cfg["yoy_change_pct"] = _pct_col()
    return dict(data=df, use_container_width=True, hide_index=True, column_config=cfg)


# ---------------------------------------------------------------------------
# Regional inequality table
# ---------------------------------------------------------------------------

def regional_table(df: pd.DataFrame) -> dict[str, Any]:
    cfg: dict = {}
    if "region" in df.columns:
        cfg["region"] = st.column_config.TextColumn("Region", width="large")
    if "gini_coefficient" in df.columns:
        cfg["gini_coefficient"] = st.column_config.NumberColumn("Gini", format="%.4f", width="small")
    if "mean_income" in df.columns:
        cfg["mean_income"] = st.column_config.NumberColumn("Mean income (₱/yr)",
                                                           format="₱%,.0f", width="medium")
    for col in ("income_share_q1", "income_share_q5"):
        if col in df.columns:
            q = col.replace("income_share_", "").upper()
            cfg[col] = st.column_config.NumberColumn(f"{q} share", format="%.1f%%", width="small")
    return dict(data=df, use_container_width=True, hide_index=True, column_config=cfg)


# ---------------------------------------------------------------------------
# Download button helper
# ---------------------------------------------------------------------------

def download_csv(df: pd.DataFrame, filename: str, label: str = "📥 Download CSV") -> None:
    """Render a download button for a DataFrame as CSV."""
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(label=label, data=csv,
                       file_name=filename, mime="text/csv")
