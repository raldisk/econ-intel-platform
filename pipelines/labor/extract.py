"""
Labor extract — loads PSA LFS (Labor Force Survey) data from a user-provided CSV.

DATA GAP NOTICE (P4 audit finding CF-V8-001):
  PH-Labor-Analysis (source repo) does NOT contain PSA LFS microdata.
  That repo is ph-ofw-analysis — a macro EDA notebook for GDP/CPI/remittances,
  which the economic pipeline already covers. See lessons.md L014.

  Real PSA LFS data requires manual download from:
    https://psa.gov.ph/content/labor-force-survey-lfs

  Provide the CSV path via cfg.LABOR_LFS_CSV to enable this pipeline.
  Without it, extract() writes an empty marker file and the pipeline
  logs a WARNING — no RuntimeError, no crash. The labor_market DuckDB
  view remains as the schema.sql placeholder stub.

Expected CSV format (when real data is provided):
  Required columns:
    survey_round      — string, e.g. "January 2024" or "2024Q1"
    region            — string, e.g. "NCR" or "Region I - Ilocos Region"
    employment_rate   — float, percent (0–100)
    unemployment_rate — float, percent (0–100)
    underemployment_rate — float, percent (0–100)

  Optional columns (passed through if present):
    labor_force_participation_rate
    population_15_plus
    survey_year
    survey_quarter

  If your LFS CSV uses different column names, add a rename mapping in
  cfg.LABOR_LFS_COLUMN_MAP (dict of {csv_col: standard_col}).

Output:
  data/raw/labor/lfs_raw.parquet  — raw rows from the CSV, no transforms
  data/raw/labor/gap.txt          — written when no CSV is available (marker file)

Interface contract:
    extract() -> None
    Never raises on missing data — logs WARNING and writes marker.
    Raises only on malformed CSV (wrong dtypes, missing required columns).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

import config as cfg

logger = logging.getLogger(__name__)

_REQUIRED_COLUMNS = {
    "survey_round",
    "region",
    "employment_rate",
    "unemployment_rate",
    "underemployment_rate",
}

_OPTIONAL_COLUMNS = [
    "labor_force_participation_rate",
    "population_15_plus",
    "survey_year",
    "survey_quarter",
]

_GAP_MESSAGE = """PSA LFS data not available.

To enable the Labor pipeline:
  1. Download the PSA LFS CSV from:
       https://psa.gov.ph/content/labor-force-survey-lfs
  2. Set cfg.LABOR_LFS_CSV to the file path.
  3. Re-run: python -m pipelines.labor.run

Expected CSV columns:
  survey_round, region, employment_rate,
  unemployment_rate, underemployment_rate

See pipelines/labor/extract.py for full format documentation.
"""


def extract() -> None:
    """
    Load PSA LFS CSV if available; write gap marker if not.

    Never raises on missing data. Raises ValueError if the CSV
    is present but missing required columns.
    """
    cfg.LABOR_RAW_DIR.mkdir(parents=True, exist_ok=True)

    lfs_csv = getattr(cfg, "LABOR_LFS_CSV", None)
    column_map = getattr(cfg, "LABOR_LFS_COLUMN_MAP", {})

    if not lfs_csv or not Path(lfs_csv).exists():
        _write_gap_marker()
        return

    csv_path = Path(lfs_csv)
    logger.info("Labor extract: loading LFS CSV from %s ...", csv_path)

    try:
        df = pd.read_csv(csv_path, dtype=str)
    except Exception as exc:
        raise ValueError(f"Labor extract: cannot read LFS CSV at {csv_path}: {exc}") from exc

    # Apply user-supplied column rename map
    if column_map:
        df = df.rename(columns=column_map)
        logger.info("Labor extract: applied column rename map: %s", column_map)

    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    missing = _REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(
            f"Labor LFS CSV is missing required columns: {sorted(missing)}. "
            f"Found: {sorted(df.columns)}. "
            "See pipelines/labor/extract.py for expected format."
        )

    out_path = cfg.LABOR_RAW_DIR / "lfs_raw.parquet"
    df.to_parquet(out_path, index=False)

    # Remove gap marker if it exists from a prior run
    gap_path = cfg.LABOR_RAW_DIR / "gap.txt"
    if gap_path.exists():
        gap_path.unlink()
        logger.info("Labor extract: removed prior gap marker.")

    logger.info(
        "Labor extract complete: %d rows, %d regions → %s",
        len(df),
        df["region"].nunique() if "region" in df.columns else 0,
        out_path,
    )


def _write_gap_marker() -> None:
    """Write gap.txt marker and log a clear WARNING."""
    gap_path = cfg.LABOR_RAW_DIR / "gap.txt"
    gap_path.write_text(_GAP_MESSAGE, encoding="utf-8")
    logger.warning(
        "Labor extract: PSA LFS CSV not configured "
        "(cfg.LABOR_LFS_CSV is None or file not found). "
        "labor_market view will remain as schema.sql placeholder. "
        "Gap marker written to: %s",
        gap_path,
    )