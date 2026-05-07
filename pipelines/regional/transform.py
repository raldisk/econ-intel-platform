"""
Regional transform — computes regional inequality metrics from FIES data.

Input:
  data/raw/regional/fies.json      — FIES household records
  data/raw/regional/poverty.json   — Poverty incidence by region × year

Output:
  data/processed/regional/regional_inequality.parquet
    Schema:
      survey_year       int64    — 2021 or 2023
      region            object   — PSA region name
      gini_coefficient  float64  — Lorenz-trapezoidal approximation
      mean_income       float64  — PHP/year, weighted mean family income
      income_share_q1   float64  — bottom quintile income share (%)
      income_share_q2   float64  — second quintile (%)
      income_share_q3   float64  — middle quintile (%)
      income_share_q4   float64  — fourth quintile (%)
      income_share_q5   float64  — top quintile income share (%)

Gini computation (ported from PH-Regional-Inequality/sql/gini_trend.sql):
  1. Sort households by total_income_php within each (survey_year, region).
  2. Assign income deciles (NTILE(10) equivalent via pd.qcut rank-based).
  3. Compute weighted decile income shares.
  4. Build Lorenz curve (cumulative income share vs. population share).
  5. Apply trapezoidal rule: Gini = 1 - 2 * Σ[(L_i + L_{i-1}) / 2 * Δp].

Income quintile shares:
  Q1 = deciles 1+2, Q2 = 3+4, Q3 = 5+6, Q4 = 7+8, Q5 = 9+10

Sample weight handling:
  If 'sample_weight' column is present, decile incomes are weighted.
  Otherwise, raw row counts are used (equal weight = 1.0 per household).
"""

from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd

import config as cfg
from db.init import PARQUET_MAP

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Gini computation
# ---------------------------------------------------------------------------

def _gini_from_fies(df_region: pd.DataFrame) -> float:
    """
    Compute Gini coefficient for a single (survey_year, region) group
    using the Lorenz trapezoidal rule.

    Args:
        df_region: DataFrame with columns ['total_income_php', 'sample_weight']
                   (all rows belong to one region × year).

    Returns:
        Gini coefficient in [0, 1]. Returns NaN if fewer than 10 households.
    """
    df = df_region.dropna(subset=["total_income_php"])
    df = df[df["total_income_php"] > 0]
    if len(df) < 10:
        return float("nan")

    weight = df["sample_weight"] if "sample_weight" in df.columns else pd.Series(
        1.0, index=df.index
    )

    # Sort by income ascending
    order = df["total_income_php"].argsort()
    inc    = df["total_income_php"].iloc[order].values
    wt     = weight.iloc[order].values

    # Cumulative population and income shares (Lorenz curve)
    cum_pop    = np.cumsum(wt)  / wt.sum()
    cum_income = np.cumsum(inc * wt) / (inc * wt).sum()

    # Prepend (0, 0) origin for the Lorenz curve
    L = np.concatenate([[0.0], cum_income])
    P = np.concatenate([[0.0], cum_pop])

    # Trapezoidal rule: area under Lorenz curve
    area_under_lorenz = float(np.trapezoid(L, P) if hasattr(np, 'trapezoid') else np.trapz(L, P))

    # Gini = 1 - 2 * area_under_lorenz
    return round(max(0.0, min(1.0, 1.0 - 2.0 * area_under_lorenz)), 4)


# ---------------------------------------------------------------------------
# Income quintile shares
# ---------------------------------------------------------------------------

def _quintile_shares(df_region: pd.DataFrame) -> dict[str, float]:
    """
    Compute income quintile shares (Q1–Q5) for a single region × year group.

    Q1 = bottom 20% (deciles 1–2)
    Q2 = 21–40%      (deciles 3–4)
    Q3 = 41–60%      (deciles 5–6)
    Q4 = 61–80%      (deciles 7–8)
    Q5 = top 20%     (deciles 9–10)

    Returns dict with keys income_share_q1 … income_share_q5 (% of total).
    All NaN if fewer than 10 households.
    """
    empty = {f"income_share_q{i}": float("nan") for i in range(1, 6)}
    df = df_region.dropna(subset=["total_income_php"])
    df = df[df["total_income_php"] > 0]
    if len(df) < 10:
        return empty

    weight = df["sample_weight"].values if "sample_weight" in df.columns else np.ones(len(df))

    # Assign income deciles by weighted rank
    # Use pd.qcut on the income column with 10 quantiles (unweighted approximation)
    # For weighted deciles, use np.searchsorted on the weighted CDF
    inc = df["total_income_php"].values
    order = np.argsort(inc)
    inc_sorted = inc[order]
    wt_sorted  = weight[order]

    cum_wt = np.cumsum(wt_sorted)
    total_wt = cum_wt[-1]
    # Decile boundaries: each 10% of total weight
    decile_edges = np.array([total_wt * i / 10 for i in range(11)])
    decile_labels = np.searchsorted(cum_wt, decile_edges[:-1], side="right") + 1
    # Map each observation to its decile (1–10)
    obs_deciles = np.searchsorted(decile_edges[1:], cum_wt - wt_sorted / 2, side="right") + 1
    obs_deciles = np.clip(obs_deciles, 1, 10)

    # Weighted income by decile
    total_weighted_income = float((inc_sorted * wt_sorted).sum())
    if total_weighted_income == 0:
        return empty

    quintile_income = np.zeros(5)
    for decile in range(1, 11):
        mask = obs_deciles == decile
        di = float((inc_sorted[mask] * wt_sorted[mask]).sum())
        quintile_idx = (decile - 1) // 2  # deciles 1-2 → Q0, 3-4 → Q1, ...
        quintile_income[quintile_idx] += di

    shares = quintile_income / total_weighted_income * 100
    return {f"income_share_q{i+1}": round(float(shares[i]), 4) for i in range(5)}


# ---------------------------------------------------------------------------
# transform()
# ---------------------------------------------------------------------------

def transform() -> None:
    """
    Read raw FIES + poverty JSON → compute regional inequality metrics
    → write regional_inequality.parquet.

    Raises:
        FileNotFoundError  — if raw JSON not found (extract not run)
        ValueError         — if FIES data is empty after loading
    """
    fies_path    = cfg.REGIONAL_RAW_DIR / "fies.json"
    poverty_path = cfg.REGIONAL_RAW_DIR / "poverty.json"

    if not fies_path.exists():
        raise FileNotFoundError(
            f"Regional FIES raw file not found: {fies_path} — run extract() first."
        )

    logger.info("Regional transform: loading FIES data ...")
    fies_raw  = json.loads(fies_path.read_text(encoding="utf-8"))
    df_fies   = pd.DataFrame(fies_raw)

    if df_fies.empty:
        raise ValueError("Regional transform: FIES JSON is empty.")

    # Normalise column names
    df_fies.columns = [c.strip().lower() for c in df_fies.columns]

    if "total_income_php" not in df_fies.columns:
        raise ValueError(
            "Regional transform: 'total_income_php' column missing from FIES data. "
            f"Found columns: {list(df_fies.columns)}"
        )

    # Load poverty data if available (used for annotation — not required for transform)
    poverty_df = None
    if poverty_path.exists():
        pov_raw   = json.loads(poverty_path.read_text(encoding="utf-8"))
        poverty_df = pd.DataFrame(pov_raw)
        if not poverty_df.empty:
            poverty_df.columns = [c.strip().lower() for c in poverty_df.columns]

    logger.info(
        "Regional transform: %d FIES rows across %d survey years × %d regions.",
        len(df_fies),
        df_fies["survey_year"].nunique() if "survey_year" in df_fies.columns else 0,
        df_fies["region_name"].nunique() if "region_name" in df_fies.columns else 0,
    )

    # Coerce dtypes
    df_fies["total_income_php"] = pd.to_numeric(df_fies["total_income_php"], errors="coerce")
    if "sample_weight" in df_fies.columns:
        df_fies["sample_weight"] = pd.to_numeric(df_fies["sample_weight"], errors="coerce").fillna(1.0)
    else:
        df_fies["sample_weight"] = 1.0

    if "survey_year" not in df_fies.columns:
        # Default to 2023 if no year column
        df_fies["survey_year"] = 2023
        logger.warning("Regional transform: 'survey_year' column not found — defaulting to 2023.")

    df_fies["survey_year"] = pd.to_numeric(df_fies["survey_year"], errors="coerce").astype("Int64")

    region_col = "region_name" if "region_name" in df_fies.columns else "region"
    if region_col not in df_fies.columns:
        raise ValueError(
            "Regional transform: no region column found. "
            f"Expected 'region_name' or 'region'. Found: {list(df_fies.columns)}"
        )

    # ---------------------------------------------------------------------------
    # Compute metrics per (survey_year, region)
    # ---------------------------------------------------------------------------
    results = []
    for (year, region), group in df_fies.groupby(["survey_year", region_col]):
        if pd.isna(year) or not region:
            continue

        gini = _gini_from_fies(group)
        quintiles = _quintile_shares(group)

        # Weighted mean income
        w = group["sample_weight"]
        inc = group["total_income_php"]
        valid = inc.notna() & (inc > 0)
        if valid.sum() > 0:
            mean_income = float((inc[valid] * w[valid]).sum() / w[valid].sum())
        else:
            mean_income = float("nan")

        row = {
            "survey_year":      int(year),
            "region":           str(region),
            "gini_coefficient": gini,
            "mean_income":      round(mean_income, 2) if not np.isnan(mean_income) else None,
        }
        row.update(quintiles)
        results.append(row)

    if not results:
        raise ValueError(
            "Regional transform: no valid groups produced. "
            "Check FIES data has 'survey_year' and region columns with data."
        )

    df_out = pd.DataFrame(results)

    # Merge poverty incidence if available (as annotation column)
    if poverty_df is not None and not poverty_df.empty:
        pov_region_col = "region_name" if "region_name" in poverty_df.columns else "region"
        if pov_region_col in poverty_df.columns and "poverty_incidence" in poverty_df.columns:
            pov_merge = poverty_df[["year", pov_region_col, "poverty_incidence"]].copy()
            pov_merge = pov_merge.rename(columns={
                "year": "survey_year",
                pov_region_col: "region",
                "poverty_incidence": "poverty_incidence_pct",
            })
            pov_merge["survey_year"] = pd.to_numeric(pov_merge["survey_year"], errors="coerce").astype("Int64")
            df_out = df_out.merge(pov_merge, on=["survey_year", "region"], how="left")
            logger.info("Regional transform: poverty incidence merged.")

    # Sort and validate
    df_out = df_out.sort_values(["survey_year", "region"]).reset_index(drop=True)

    out_path = PARQUET_MAP["REGIONAL_PARQUET"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_parquet(out_path, index=False)

    logger.info(
        "Regional transform complete: %d rows | years=%s | %d regions → %s",
        len(df_out),
        sorted(df_out["survey_year"].dropna().unique().tolist()),
        df_out["region"].nunique(),
        out_path,
    )

    # Summary log: Gini range
    valid_gini = df_out["gini_coefficient"].dropna()
    if not valid_gini.empty:
        logger.info(
            "Gini range: %.4f – %.4f (mean %.4f)",
            valid_gini.min(), valid_gini.max(), valid_gini.mean(),
        )