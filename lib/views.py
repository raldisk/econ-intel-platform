"""
lib/views.py — Single source of truth for view metadata.

All view-aware layers import from here:
  - api/routes/data.py      → ALLOWED_VIEWS (security guard)
  - api/routes/status.py    → SYNTHETIC_PIPELINES (disclosure)
  - apps/dash_app.py        → VIEW_AXIS_HINTS, ALLOWED_VIEWS
  - apps/streamlit_app.py   → VIEW_AXIS_HINTS, ALLOWED_VIEWS
  - GET /views/meta          → serialises VIEW_AXIS_HINTS for Next.js

Adding a new pipeline:
  1. Add to REQUIRED_OBJECTS in db/init.py  (bootstrap assertion)
  2. Add to VIEW_AXIS_HINTS here            (axis metadata)
  ALLOWED_VIEWS is derived from REQUIRED_OBJECTS — no manual update needed.
"""

from __future__ import annotations

from db.init import REQUIRED_OBJECTS

# ---------------------------------------------------------------------------
# Security allowlist — derived, not hand-maintained.
# The API route guards against table-name injection using this set.
# ---------------------------------------------------------------------------

ALLOWED_VIEWS: frozenset[str] = REQUIRED_OBJECTS


# ---------------------------------------------------------------------------
# Axis hints — canonical date and value columns per view.
# Used server-side for KPI computation and client-side for chart defaults.
# Served to the Next.js frontend via GET /views/meta.
# ---------------------------------------------------------------------------

VIEW_AXIS_HINTS: dict[str, dict[str, str]] = {
    "psx_prices":               {"date_col": "date",          "value_col": "close"},
    "bsp_policy_rate":          {"date_col": "decision_date", "value_col": "overnight_rp"},
    "fx_rates":                 {"date_col": "rate_date",     "value_col": "rate"},
    "stg_fx_rates":             {"date_col": "rate_date",     "value_col": "rate"},
    "fx_volatility":            {"date_col": "rate_date",     "value_col": "annualized_vol"},
    "cpi_trend":                {"date_col": "period_date",   "value_col": "inflation_pct"},
    "gdp_tracker":              {"date_col": "period_year",   "value_col": "gdp_usd_bn"},
    "remittance_trend":         {"date_col": "period_date",   "value_col": "remittances_usd_mn"},
    "economic_dashboard":       {"date_col": "period_year",   "value_col": "gdp_usd_bn"},
    "labor_market":             {"date_col": "survey_date",   "value_col": "unemployment_rate"},
    "regional_inequality":      {"date_col": "survey_year",   "value_col": "gini_coefficient"},
    "commodity_prices":         {"date_col": "price_date",    "value_col": "retail_price_php"},
    "food_price_decomposition": {"date_col": "period",        "value_col": "observed"},
    "price_trend_by_commodity": {"date_col": "month",         "value_col": "avg_price"},
    "social_sentiment":         {"date_col": "scored_at",     "value_col": "sentiment_score"},
    "sentiment_topic_trend":    {"date_col": "obs_date",      "value_col": "avg_sentiment"},
    "pipeline_runs":            {"date_col": "run_at",        "value_col": "rows_affected"},
    "psx_vs_bsp":               {"date_col": "date",          "value_col": "close"},
    "cpi_vs_fx":                {"date_col": "period_date",   "value_col": "cpi_yoy"},
    "real_exchange_rate":       {"date_col": "month",         "value_col": "real_rate"},
    "coa_budget_utilization":   {"date_col": "fiscal_year",   "value_col": "disbursement_rate"},
    "coa_low_utilizers":        {"date_col": "fiscal_year",   "value_col": "disbursement_rate"},
}


# ---------------------------------------------------------------------------
# Synthetic data map — pipelines that fall back to generated data when
# real credentials / files are absent.  Checked at runtime by GET /status.
# Keys match pipeline names written to pipeline_runs.pipeline column.
# ---------------------------------------------------------------------------

def synthetic_status() -> dict[str, bool]:
    """
    Return a dict mapping pipeline name → True if currently using synthetic data.
    Evaluated at request time so config changes take effect without restart.
    """
    import os
    import config as cfg

    return {
        "psx":       False,  # always live via yfinance
        "bsp":       False,  # always live via BSP scrape
        "fx":        False,  # always live via BSP RERB / Frankfurter
        "economic":  False,  # always live via PSA OpenSTAT + World Bank
        "labor":     cfg.LABOR_LFS_CSV is None,
        "regional":  cfg.REGIONAL_DATA_DIR is None,
        "prices":    cfg.PRICES_PSA_CSV is None,
        "sentiment": not bool(os.environ.get("REDDIT_CLIENT_ID")),
        "coa":       cfg.COA_PDF_DIR is None,
    }
