"""
COA transform — normalize raw COA records and flag LGU/agency outliers.

Input:
  data/raw/coa/coa_raw.json

Output:
  data/processed/coa/coa_budget_utilization.parquet
    Schema:
      fiscal_year          int64    — e.g. 2023
      agency               object   — full agency name
      agency_code          object   — short code (DepEd, DOH, etc.)
      agency_type          object   — 'national' | 'lgu' | 'gocc'
      appropriation_php    float64  — total appropriation (₱)
      obligation_php       float64  — obligations incurred (₱)
      disbursement_php     float64  — actual disbursements (₱)
      disbursement_rate    float64  — disbursement / appropriation (%)
      obligation_rate      float64  — obligation / appropriation (%)
      region               object   — PSA region (LGU records only)
      source               object   — PDF filename or 'SYNTHETIC_FALLBACK'
      is_low_utilizer      bool     — disbursement_rate < threshold (outlier flag)
      is_high_utilizer     bool     — disbursement_rate > 95% (possible inflated)
      zscore_disbursement  float64  — z-score within fiscal_year × agency_type group
      notes                object   — extraction notes

Outlier detection:
  is_low_utilizer:  disbursement_rate < mean - 1.5σ within peer group
                    (fiscal_year × agency_type) — flags underperformers
  is_high_utilizer: disbursement_rate > 95% — flags potential
                    obligation inflation or rushed year-end spending
  zscore:           (rate - group_mean) / group_std — enables ranking
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

import config as cfg

logger = logging.getLogger(__name__)

_LOW_UTILIZER_THRESHOLD_PCT = 70.0    # below 70% disbursement is flagged
_HIGH_UTILIZER_THRESHOLD_PCT = 95.0   # above 95% may indicate end-of-year rush


def _flag_outliers(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add is_low_utilizer, is_high_utilizer, zscore_disbursement columns.
    Groups by fiscal_year × agency_type for peer comparison.
    """
    df = df.copy()

    # Peer-group z-score
    group = df.groupby(["fiscal_year", "agency_type"])["disbursement_rate"]
    df["peer_mean"] = group.transform("mean")
    df["peer_std"]  = group.transform("std").fillna(1.0)
    df["zscore_disbursement"] = (
        (df["disbursement_rate"] - df["peer_mean"]) / df["peer_std"]
    ).round(4)

    # Low utilizer: below 70% OR more than 1.5σ below peer mean
    df["is_low_utilizer"] = (
        (df["disbursement_rate"] < _LOW_UTILIZER_THRESHOLD_PCT) |
        (df["zscore_disbursement"] < -1.5)
    )

    # High utilizer: above 95%
    df["is_high_utilizer"] = df["disbursement_rate"] > _HIGH_UTILIZER_THRESHOLD_PCT

    return df.drop(columns=["peer_mean", "peer_std"])


def transform() -> None:
    """
    Load coa_raw.json, normalize, flag outliers, write parquet.
    """
    raw_path = cfg.COA_RAW_DIR / "coa_raw.json"
    if not raw_path.exists():
        raise FileNotFoundError(
            f"coa_raw.json not found at {raw_path} — run extract() first."
        )

    records = json.loads(raw_path.read_text(encoding="utf-8"))
    if not records:
        raise ValueError("coa_raw.json is empty — extract() produced no records.")

    df = pd.DataFrame(records)

    # Type coercion
    df["fiscal_year"]       = df["fiscal_year"].astype("Int64")
    df["disbursement_rate"] = pd.to_numeric(df["disbursement_rate"], errors="coerce")
    df["obligation_rate"]   = pd.to_numeric(df["obligation_rate"],   errors="coerce")
    df["appropriation_php"] = pd.to_numeric(df["appropriation_php"], errors="coerce")
    df["obligation_php"]    = pd.to_numeric(df["obligation_php"],     errors="coerce")
    df["disbursement_php"]  = pd.to_numeric(df["disbursement_php"],   errors="coerce")

    # Drop rows with no disbursement_rate — can't flag what we can't measure
    before = len(df)
    df = df[df["disbursement_rate"].notna()].copy()
    if before - len(df):
        logger.warning(
            "COA transform: dropped %d rows with null disbursement_rate",
            before - len(df),
        )

    # Outlier flags
    df = _flag_outliers(df)

    # Final column order
    cols = [
        "fiscal_year", "agency", "agency_code", "agency_type",
        "appropriation_php", "obligation_php", "disbursement_php",
        "disbursement_rate", "obligation_rate",
        "is_low_utilizer", "is_high_utilizer", "zscore_disbursement",
        "region", "source", "notes",
    ]
    df = df[[c for c in cols if c in df.columns]]

    cfg.COA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out = cfg.COA_PROCESSED_DIR / "coa_budget_utilization.parquet"
    df.to_parquet(out, index=False)

    low  = df["is_low_utilizer"].sum()
    high = df["is_high_utilizer"].sum()
    logger.info(
        "COA transform complete: %d records → %s | "
        "low_utilizers=%d | high_utilizers=%d | years=%s",
        len(df), out, low, high,
        sorted(df["fiscal_year"].dropna().unique().tolist()),
    )
