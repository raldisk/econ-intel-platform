"""
Regional extract — loads PSA FIES and poverty data; generates synthetic fallback if unavailable.

Data sources (all PSA — require manual download):
  data/raw/regional/fies_2021.csv             — Family Income and Expenditure Survey 2021
  data/raw/regional/fies_2023.csv             — Family Income and Expenditure Survey 2023
  data/raw/regional/poverty_provincial.csv    — Official Poverty Statistics (all years)

If real PSA CSVs are not present, synthetic data is generated automatically
using the same logic and anchored values as PH-Regional-Inequality's
download_data.py::generate_sample_data(). The synthetic data follows the
2021 and 2023 PSA poverty statistics exactly for regional poverty incidence
and uses realistic lognormal income distributions by region.

Raw output:
  data/raw/regional/fies.json         — FIES household records (list of dicts)
  data/raw/regional/poverty.json      — Poverty incidence by region × year

Interface contract:
    extract() -> None
    Always produces output (real or synthetic).
    Logs clearly which data source was used.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

import config as cfg

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PSA 17 regions — codes + names (PSGC 2023 administrative classification)
# ---------------------------------------------------------------------------

_REGIONS = [
    ("01",   "Region I - Ilocos Region"),
    ("02",   "Region II - Cagayan Valley"),
    ("03",   "Region III - Central Luzon"),
    ("04A",  "Region IVA - CALABARZON"),
    ("04B",  "Region IVB - MIMAROPA"),
    ("05",   "Region V - Bicol Region"),
    ("06",   "Region VI - Western Visayas"),
    ("07",   "Region VII - Central Visayas"),
    ("08",   "Region VIII - Eastern Visayas"),
    ("09",   "Region IX - Zamboanga Peninsula"),
    ("10",   "Region X - Northern Mindanao"),
    ("11",   "Region XI - Davao Region"),
    ("12",   "Region XII - SOCCSKSARGEN"),
    ("13",   "Region XIII - Caraga"),
    ("BARMM","BARMM"),
    ("CAR",  "CAR"),
    ("NCR",  "NCR"),
]

# Official PSA poverty incidence anchors (2021, 2023)
_POV_2021 = [16.8, 16.1, 10.9, 9.9, 26.8, 37.1, 21.3, 23.0, 37.4,
             33.6, 22.3, 18.1, 25.7, 32.5, 61.2, 22.5, 4.1]
_POV_2023 = [15.2, 14.8,  9.4, 8.7, 24.1, 33.2, 18.5, 20.2, 34.7,
             30.1, 19.8, 15.9, 22.4, 29.8, 37.2, 20.3, 3.5]

# Mean family income anchors (PHP thousands/year) — approximated from PSA FIES 2023
_INCOME_MEAN_K = [310, 295, 420, 450, 240, 220, 290, 310, 210,
                  195, 320, 350, 275, 230, 160, 280, 580]


# ---------------------------------------------------------------------------
# Synthetic data generator (ported from PH-Regional-Inequality/scripts/download_data.py)
# ---------------------------------------------------------------------------

def _generate_synthetic_fies(rng: np.random.Generator) -> list[dict]:
    """
    Generate realistic synthetic FIES household records for all 17 regions,
    survey years 2021 and 2023. Matches the PH-Regional-Inequality schema.
    ~200 synthetic households per region per year.
    """
    rows: list[dict] = []
    for year, pov_list in [(2021, _POV_2021), (2023, _POV_2023)]:
        for i, (code, name) in enumerate(_REGIONS):
            base = _INCOME_MEAN_K[i] * 1000
            for _ in range(200):
                income = max(50_000, rng.lognormal(np.log(base), 0.6))
                rows.append({
                    "survey_year":         year,
                    "region_code":         code,
                    "region_name":         name,
                    "total_income_php":    round(float(income), 2),
                    "total_expenditure":   round(float(income * rng.uniform(0.70, 0.95)), 2),
                    "food_expenditure":    round(float(income * rng.uniform(0.25, 0.45)), 2),
                    "edu_expenditure":     round(float(income * rng.uniform(0.02, 0.08)), 2),
                    "health_expenditure":  round(float(income * rng.uniform(0.02, 0.06)), 2),
                    "housing_expenditure": round(float(income * rng.uniform(0.08, 0.18)), 2),
                    "per_capita_income":   round(float(income / rng.integers(3, 8)), 2),
                    "household_size":      round(float(rng.uniform(3.5, 6.5)), 2),
                    "sample_weight":       round(float(rng.uniform(0.5, 2.5)), 4),
                    "synthetic":           True,
                })
    return rows


def _generate_synthetic_poverty() -> list[dict]:
    """
    Generate poverty incidence records anchored to official PSA 2021 and 2023 values.
    """
    rows: list[dict] = []
    for year, pov_list in [(2021, _POV_2021), (2023, _POV_2023)]:
        for i, (code, name) in enumerate(_REGIONS):
            rows.append({
                "year":               year,
                "region_code":        code,
                "region_name":        name,
                "province_code":      None,
                "province_name":      None,
                "poverty_incidence":  pov_list[i],
                "poverty_threshold":  round(12_000 + (i * 200), 2),
                "poverty_gap":        round(pov_list[i] * 0.35, 2),
                "income_gap":         round(pov_list[i] * 0.45, 2),
                "synthetic":          True,
            })
    return rows


# ---------------------------------------------------------------------------
# Real data loaders
# ---------------------------------------------------------------------------

def _load_real_fies(path_2021: Path, path_2023: Path) -> Optional[list[dict]]:
    """Load real PSA FIES CSVs and combine. Returns None if both paths missing."""
    frames = []
    for path, year in [(path_2021, 2021), (path_2023, 2023)]:
        if not path.exists():
            logger.warning("Regional extract: FIES CSV not found: %s", path)
            continue
        df = pd.read_csv(path)
        df["survey_year"] = year
        df["synthetic"]   = False
        frames.append(df)

    if not frames:
        return None
    combined = pd.concat(frames, ignore_index=True)
    logger.info("Regional extract: loaded %d real FIES rows.", len(combined))
    return combined.to_dict(orient="records")


def _load_real_poverty(path: Path) -> Optional[list[dict]]:
    """Load real PSA poverty CSV. Returns None if path missing."""
    if not path.exists():
        return None
    df = pd.read_csv(path)
    df["synthetic"] = False
    logger.info("Regional extract: loaded %d real poverty rows.", len(df))
    return df.to_dict(orient="records")


# ---------------------------------------------------------------------------
# extract() — public entry point
# ---------------------------------------------------------------------------

def extract() -> None:
    """
    Load PSA FIES and poverty data; fall back to synthetic if not available.

    Checks cfg.REGIONAL_DATA_DIR for:
      fies_2021.csv, fies_2023.csv, poverty_provincial.csv

    If all three are absent, generates synthetic data automatically.
    Logs clearly which source was used.

    Outputs:
      data/raw/regional/fies.json      — FIES household records
      data/raw/regional/poverty.json   — Poverty incidence by region × year
    """
    cfg.REGIONAL_RAW_DIR.mkdir(parents=True, exist_ok=True)

    real_dir = getattr(cfg, "REGIONAL_DATA_DIR", None) or cfg.REGIONAL_RAW_DIR
    fies_2021_path  = Path(real_dir) / "fies_2021.csv"
    fies_2023_path  = Path(real_dir) / "fies_2023.csv"
    poverty_path    = Path(real_dir) / "poverty_provincial.csv"

    # Attempt real data load
    fies_records    = _load_real_fies(fies_2021_path, fies_2023_path)
    poverty_records = _load_real_poverty(poverty_path)

    # Fall back to synthetic where real data is absent
    rng = np.random.default_rng(42)
    used_synthetic = False

    if fies_records is None:
        logger.info(
            "Regional extract: no real FIES CSVs found — generating synthetic data. "
            "To use real data, set cfg.REGIONAL_DATA_DIR and provide: "
            "fies_2021.csv, fies_2023.csv"
        )
        fies_records = _generate_synthetic_fies(rng)
        used_synthetic = True

    if poverty_records is None:
        logger.info(
            "Regional extract: no real poverty CSV found — generating synthetic data "
            "anchored to official PSA 2021 and 2023 poverty incidence values."
        )
        poverty_records = _generate_synthetic_poverty()
        used_synthetic = True

    if used_synthetic:
        logger.warning(
            "Regional extract: using synthetic data. "
            "Gini computations and income statistics are realistic approximations — "
            "not official PSA figures. Download real FIES from "
            "https://psa.gov.ph/statistics/income-expenditure to replace."
        )
    else:
        logger.info("Regional extract: using real PSA data.")

    # Write raw JSON outputs
    fies_out    = cfg.REGIONAL_RAW_DIR / "fies.json"
    poverty_out = cfg.REGIONAL_RAW_DIR / "poverty.json"

    fies_out.write_text(
        json.dumps(fies_records, default=str, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    poverty_out.write_text(
        json.dumps(poverty_records, default=str, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    logger.info(
        "Regional extract complete: %d FIES records, %d poverty records → %s",
        len(fies_records), len(poverty_records), cfg.REGIONAL_RAW_DIR,
    )