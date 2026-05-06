"""
PH-Dashboard central configuration.

All paths, TTLs, schedule intervals, and source URLs live here.
Import `cfg` anywhere in the codebase — do not hard-code paths.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional  # PATCH FINDING-003: required for Optional[Path] annotations

# ---------------------------------------------------------------------------
# Root paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parent.resolve()

DATA_RAW       = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
DATA_CACHE     = ROOT / "data" / "cache"

DB_PATH        = ROOT / "db" / "duckdb_local.db"
SCHEMA_PATH    = ROOT / "db" / "schema.sql"

# ---------------------------------------------------------------------------
# PSX — Philippine Stock Exchange
# ---------------------------------------------------------------------------

# PSEi index ticker on yfinance
PSX_INDEX_TICKER = "PSEi.PS"  # fallback: use PSEI or ^PSE
#PSX_INDEX_TICKER = "PSEI.PS"

# Blue-chip PSE-listed equities (Yahoo Finance suffix: .PS)
PSX_TICKERS: list[str] = [
    "SM.PS",    # SM Investments
    "ALI.PS",   # Ayala Land
    "BDO.PS",   # BDO Unibank
    "AC.PS",    # Ayala Corporation
    "BPI.PS",   # Bank of the Philippine Islands
    "JFC.PS",   # Jollibee Foods
    "MER.PS",   # Manila Electric
    "TEL.PS",   # PLDT
    "GLO.PS",   # Globe Telecom
    "MBT.PS",   # Metrobank
    "URC.PS",   # Universal Robina
    "ICT.PS",   # International Container Terminal
    "PGOLD.PS", # Puregold Price Club
    "RLC.PS",   # Robinsons Land
    "DMC.PS",   # DMCI Holdings
]

PSX_START_DATE    = "2015-01-01"
PSX_RAW_DIR       = DATA_RAW / "psx"
PSX_PROCESSED_DIR = DATA_PROCESSED / "psx"

# Technical indicator parameters
PSX_RSI_PERIOD    = 14
PSX_MA_SHORT      = 20
PSX_MA_LONG       = 50
PSX_VOL_ZSCORE_WINDOW = 20

# ---------------------------------------------------------------------------
# BSP — Bangko Sentral ng Pilipinas
# ---------------------------------------------------------------------------

BSP_KEY_RATE_URL = (
    "https://www.bsp.gov.ph/monetary_policy/key_rates.aspx"
)
BSP_TABLE12_URL = (
    "https://www.bsp.gov.ph/statistics/external/tab12_pus.aspx"
)
BSP_TABLE13_URL = (
    "https://www.bsp.gov.ph/statistics/external/tab13_php.aspx"
)
BSP_START_YEAR    = 2010
BSP_RAW_DIR       = DATA_RAW / "bsp"
BSP_PROCESSED_DIR = DATA_PROCESSED / "bsp"

# ---------------------------------------------------------------------------
# PSA — Philippine Statistics Authority
# ---------------------------------------------------------------------------

PSA_BASE_URL     = "https://openstat.psa.gov.ph/PXWeb/api/v1/en/DB"
PSA_TIMEOUT      = 60   # PSA API is notoriously slow
PSA_RAW_DIR      = DATA_RAW / "psa"
PSA_PROCESSED_DIR = DATA_PROCESSED / "psa"

# ---------------------------------------------------------------------------
# FX
# ---------------------------------------------------------------------------

FX_RAW_DIR       = DATA_RAW / "fx"
FX_PROCESSED_DIR = DATA_PROCESSED / "fx"

# ---------------------------------------------------------------------------
# On-demand cache TTLs (seconds)
# ---------------------------------------------------------------------------

# PATCH FINDING-004: TTL_PRICES removed here (duplicate). Canonical typed
# definition lives in the Prices section below (TTL_PRICES: int = 6 * 3600).
TTL_FX_LIVE  = 3600         # 1 hour  — intraday FX
TTL_PSA      = 24 * 3600    # 24 hours — PSA API

# ---------------------------------------------------------------------------
# HTTP defaults
# ---------------------------------------------------------------------------

HTTP_TIMEOUT    = 30
HTTP_MAX_RETRIES = 3
HTTP_BACKOFF_BASE = 2.0

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; ph-dashboard/1.0; "
        "+https://github.com/raldisk/PH-Dashboard)"
    )
}

# ---------------------------------------------------------------------------
# APScheduler jobs registry
# Used by scheduler/cron_jobs.py
# ---------------------------------------------------------------------------

SCHEDULE = [
    {
        "id":       "psx_daily",
        "module":   "pipelines.psx.run",
        "trigger":  "cron",
        "hour":     18,
        "minute":   30,
        "timezone": "Asia/Manila",
    },
    {
        "id":       "fx_daily",
        "module":   "pipelines.fx.run",
        "trigger":  "cron",
        "hour":     9,
        "minute":   0,
        "timezone": "Asia/Manila",
    },
    {
        "id":       "bsp_monthly",
        "module":   "pipelines.bsp.run",
        "trigger":  "cron",
        "day":      1,
        "hour":     8,
        "minute":   0,
        "timezone": "Asia/Manila",
    },
    {
        "id":       "prices_interval",
        "module":   "pipelines.prices.run",
        "trigger":  "interval",
        "hours":    6,
    },
    {
        "id":       "sentiment_interval",
        "module":   "pipelines.sentiment.run",
        "trigger":  "interval",
        "hours":    4,
    },
]

# Static pipelines — CLI only (no scheduler entry):
# python -m pipelines.labor.run
# python -m pipelines.regional.run
# python -m pipelines.economic.run


# ---------------------------------------------------------------------------
# Labor — PSA LFS pipeline
# ---------------------------------------------------------------------------

LABOR_RAW_DIR       = DATA_RAW / "labor"
LABOR_PROCESSED_DIR = DATA_PROCESSED / "labor"

# Path to a manually-downloaded PSA LFS CSV.
# If None, the labor pipeline runs but writes an empty parquet (data gap).
# Set this to enable the Labor page in the dashboard.
# Expected format: survey_round, region, employment_rate,
#                  unemployment_rate, underemployment_rate
LABOR_LFS_CSV: Optional[Path] = None

# Optional column rename map if your LFS CSV uses different column names.
# Example: {"Quarter": "survey_round", "Region": "region", "UR": "unemployment_rate"}
LABOR_LFS_COLUMN_MAP: dict = {}

# ---------------------------------------------------------------------------
# Regional — PSA FIES + poverty pipeline
# ---------------------------------------------------------------------------

REGIONAL_RAW_DIR       = DATA_RAW / "regional"
REGIONAL_PROCESSED_DIR = DATA_PROCESSED / "regional"

# Directory containing real PSA FIES CSVs. If None or files are absent,
# the pipeline falls back to synthetic data anchored to official PSA values.
# Expected files: fies_2021.csv, fies_2023.csv, poverty_provincial.csv
# Download from: https://psa.gov.ph/statistics/income-expenditure
REGIONAL_DATA_DIR: Optional[Path] = None

# ---------------------------------------------------------------------------
# Prices — PSA commodity prices + DOE fuel (Phase 5)
# ---------------------------------------------------------------------------

PRICES_RAW_DIR       = DATA_RAW / "prices"
PRICES_PROCESSED_DIR = DATA_PROCESSED / "prices"

# TTL for prices on-demand fetch cache (seconds).
# Prices refresh is scheduled every 6 hours via APScheduler;
# this TTL governs the ttl_cache layer inside extract().
TTL_PRICES: int = 6 * 3600  # 6 hours

# Path to a manually-downloaded PSA Price Situationer CSV.
# Expected format: price_date, phase, commodity, commodity_slug,
#                  retail_price_php, unit, region, source, scrape_date
# If None or file absent, extract() generates synthetic data (seeded, reproducible).
# Download from: https://psa.gov.ph/statistics/price-situationer/selected-agri-commodities
PRICES_PSA_CSV: Optional[Path] = None

# Path to a manually-downloaded DOE Weekly Oil Monitor CSV.
# Expected format: price_date, fuel_type, price_php, region, source
# If None, extract() generates synthetic DOE data.
# Download from: https://www.doe.gov.ph/weekly-retail-pump-prices
PRICES_DOE_CSV: Optional[Path] = None

# ---------------------------------------------------------------------------
# Sentiment — Philippine economic topic sentiment (Phase 6)
# ---------------------------------------------------------------------------

SENTIMENT_RAW_DIR       = DATA_RAW / "sentiment"
SENTIMENT_PROCESSED_DIR = DATA_PROCESSED / "sentiment"

# Reddit API credentials (optional — set via environment variables, not here).
# Required for live Reddit fetch:
#   REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT
# If absent, extract() falls back to synthetic data automatically.
# Register at: https://www.reddit.com/prefs/apps

# Twitter/X API credential (optional — set via environment variable).
# Required for live Twitter fetch:
#   TWITTER_BEARER_TOKEN
# Note: Twitter Academic API tier required for historical data.
# Live Twitter fetch is a stub in this version — set bearer token if available.

# Trailing days for synthetic fallback (covers when no API credentials are set).
SENTIMENT_SYNTHETIC_DAYS: int = 90   # trailing 90 days at 4-hour intervals

# Hardware constraint note: Intel Pentium CPU.
# transformers + torch (BERT/XLM-RoBERTa) are NOT viable:
# inference time 10+ minutes per batch.
# This pipeline uses VADER exclusively: sub-millisecond per text, zero GPU dependency.
# SENTIMENT_MODEL is kept as a doc constant only — NOT used at runtime.
SENTIMENT_MODEL: str = "vaderSentiment"  # VADER-only; BERT/RoBERTa excluded

# ---------------------------------------------------------------------------
COA_RAW_DIR       = DATA_RAW / "coa"
COA_PROCESSED_DIR = DATA_PROCESSED / "coa"

# Directory containing COA Annual Audit Report PDFs.
# If None or directory absent, extract() uses synthetic fallback.
# Download from: https://www.coa.gov.ph/index.php/reports/annual-audit-reports
# Naming: <AgencyCode>-<FiscalYear>-AAR.pdf (e.g., DepEd-2023-AAR.pdf)
COA_PDF_DIR: Optional[Path] = None

# ---------------------------------------------------------------------------
# PARQUET_MAP addition (append to PARQUET_MAP dict in db/init.py)
# ---------------------------------------------------------------------------
# "COA_PARQUET": DATA_PROCESSED / "coa" / "coa_budget_utilization.parquet",
#
# Also add stub view to db/schema.sql:
#   coa_budget_utilization — columns: fiscal_year, agency, agency_code,
#                            agency_type, appropriation_php, obligation_php,
#                            disbursement_php, disbursement_rate,
#                            obligation_rate, is_low_utilizer, is_high_utilizer,
#                            zscore_disbursement, region, source, notes
#
# Update REQUIRED_OBJECTS count in db/init.py: 21 → 22

# ---------------------------------------------------------------------------
# Dash explorer (Phase 10)
# ---------------------------------------------------------------------------

DASH_HOST: str = "127.0.0.1"
DASH_PORT: int = 8050
DASH_DEBUG: bool = False

# ---------------------------------------------------------------------------
# FX — additional URL constants (BSP RERB + Frankfurter fallback)
# ---------------------------------------------------------------------------

BSP_RERB_URL      = "https://www.bsp.gov.ph/Statistics/Rates/day99_data.aspx"
FRANKFURTER_URL   = "https://api.frankfurter.app"
FX_START_YEAR     = 2010

# ---------------------------------------------------------------------------
# Economic pipeline constants (missing from V6 base config)
# ---------------------------------------------------------------------------
ECONOMIC_RAW_DIR       = DATA_RAW / "economic"
ECONOMIC_PROCESSED_DIR = DATA_PROCESSED / "economic"
ECONOMIC_START_YEAR    = 2000
BSP_REMITTANCE_CSV     = None   # Optional Path to BSP monthly remittances CSV

# World Bank API
WORLD_BANK_BASE_URL  = "https://api.worldbank.org/v2"
WORLD_BANK_PER_PAGE  = 100
