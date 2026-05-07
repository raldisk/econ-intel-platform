"""
Labor transform — converts raw LFS parquet to labor_market schema.

Input:
  data/raw/labor/lfs_raw.parquet   — written by extract() when LFS CSV provided
  data/raw/labor/gap.txt           — written by extract() when no CSV available

Output:
  data/processed/labor/labor_market.parquet
    Columns:
      survey_round        object    — e.g. "January 2024"
      region              object    — PSA region name
      employment_rate     float64   — percent (0–100)
      unemployment_rate   float64   — percent (0–100)
      underemployment_rate float64  — percent (0–100)

Gap behavior:
  If gap.txt exists and lfs_raw.parquet does not, writes an empty parquet
  with the correct schema. The load step registers this as the labor_market
  view, which returns zero rows — the dashboard page shows "No data available."
  No exception is raised; the pipeline_runs log records status='success' with
  rows_affected=0. This is intentional — a data gap is not a pipeline failure.
"""

from __future__ import annotations

import logging

import pandas as pd

import config as cfg
from db.init import PARQUET_MAP

logger = logging.getLogger(__name__)

_SCHEMA: dict[str, str] = {
    "survey_round":          "object",
    "region":                "object",
    "employment_rate":       "float64",
    "unemployment_rate":     "float64",
    "underemployment_rate":  "float64",
}

_OPTIONAL_PASSTHROUGH = [
    "labor_force_participation_rate",
    "population_15_plus",
    "survey_year",
    "survey_quarter",
]


def transform() -> None:
    """
    Convert raw LFS parquet to the labor_market schema.

    If no raw parquet exists (data gap), writes an empty parquet with the
    correct schema and logs a WARNING. Does not raise.
    """
    raw_path = cfg.LABOR_RAW_DIR / "lfs_raw.parquet"
    gap_path = cfg.LABOR_RAW_DIR / "gap.txt"
    out_path = PARQUET_MAP["LABOR_PARQUET"]
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not raw_path.exists():
        # Data gap — write empty parquet with correct schema
        if gap_path.exists():
            logger.warning(
                "Labor transform: no LFS data available (gap marker present). "
                "Writing empty labor_market.parquet. "
                "Provide cfg.LABOR_LFS_CSV to populate this pipeline."
            )
        else:
            logger.warning(
                "Labor transform: lfs_raw.parquet not found and no gap marker. "
                "Run extract() first. Writing empty parquet."
            )
        _write_empty(out_path)
        return

    logger.info("Labor transform: reading %s ...", raw_path)
    df = pd.read_parquet(raw_path)

    # Coerce required columns to correct dtypes
    for col, dtype in _SCHEMA.items():
        if col in df.columns:
            if dtype == "float64":
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
            else:
                df[col] = df[col].astype(str).str.strip()
        else:
            # Missing required column — fill with appropriate null
            logger.warning(
                "Labor transform: required column '%s' not found — filling with null.", col
            )
            df[col] = None if dtype == "object" else float("nan")

    # Passthrough optional columns if present
    keep_cols = list(_SCHEMA.keys()) + [
        c for c in _OPTIONAL_PASSTHROUGH if c in df.columns
    ]
    df = df[keep_cols]

    # Drop rows where all three rate columns are null
    rate_cols = ["employment_rate", "unemployment_rate", "underemployment_rate"]
    df = df.dropna(subset=rate_cols, how="all")

    # Validate rate ranges: 0–100
    for col in rate_cols:
        out_of_range = df[col].between(0, 100, inclusive="both") == False  # noqa: E712
        bad_count = (~df[col].isna() & out_of_range).sum()
        if bad_count > 0:
            logger.warning(
                "Labor transform: %d rows have %s outside 0–100 range — keeping but flagging.",
                bad_count, col,
            )

    df = df.sort_values(["survey_round", "region"]).reset_index(drop=True)
    df.to_parquet(out_path, index=False)

    logger.info(
        "Labor transform complete: %d rows | %d regions | %d survey rounds → %s",
        len(df),
        df["region"].nunique(),
        df["survey_round"].nunique(),
        out_path,
    )


def _write_empty(out_path) -> None:
    """Write empty parquet with labor_market schema."""
    df = pd.DataFrame({col: pd.Series(dtype=dtype)
                       for col, dtype in _SCHEMA.items()})
    df.to_parquet(out_path, index=False)
    logger.info("Labor transform: empty labor_market.parquet written → %s", out_path)