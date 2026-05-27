"""
DuckDB initialization — bootstraps duckdb_local.db from schema.sql.

Run once before starting any app:
    python -m db.init

Re-runnable: all CREATE statements use IF NOT EXISTS or CREATE OR REPLACE.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import duckdb

import config as cfg

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Required objects — must all be present after a successful bootstrap.
# init_db() raises RuntimeError if any are missing.
# ---------------------------------------------------------------------------

REQUIRED_OBJECTS: frozenset[str] = frozenset({
    # Core tables
    "pipeline_runs",
    # PSX
    "psx_prices",
    "psx_vs_bsp",
    # BSP
    "bsp_policy_rate",
    # FX
    "fx_rates",
    "stg_fx_rates",
    "fx_volatility",
    "real_exchange_rate",
    "cpi_vs_fx",
    # Economic
    "cpi_trend",
    "gdp_tracker",
    "remittance_trend",
    "economic_dashboard",
    # Labor
    "labor_market",
    # Regional
    "regional_inequality",
    # Prices
    "commodity_prices",
    "food_price_decomposition",
    "price_trend_by_commodity",
    # Sentiment
    "social_sentiment",
    "sentiment_topic_trend",
    # COA
    "coa_budget_utilization",
    "coa_low_utilizers",
    # ── Edge A: macro lakehouse enrichment (optional; empty view when R2 absent)
    "macro_lakehouse_indicators",
    # ── Edge C: BSP credit exposure (optional; empty view when R3 absent)
    "credit_exposure",
})


def init_db() -> None:
    """
    Bootstrap DuckDB database:
      1. Create data directories.
      2. Read schema.sql, substitute parquet paths.
      3. Execute all DDL statements — any failure is fatal.
      4. Assert all required views and tables are registered.
    """
    # Ensure all processed subdirs exist
    for path in PARQUET_MAP.values():
        path.parent.mkdir(parents=True, exist_ok=True)

    schema_sql = cfg.SCHEMA_PATH.read_text(encoding="utf-8")

    cfg.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(cfg.DB_PATH))
    try:
        statements = [s.strip() for s in schema_sql.split(";") if s.strip()]
        for stmt in statements:
            try:
                con.execute(stmt)
            except Exception as exc:
                # DDL failures are FATAL — a broken schema is worse than no schema.
                # Log the full statement for diagnosis, then re-raise.
                logger.error(
                    "Schema statement FAILED (fatal):\n  %s\n  Error: %s",
                    stmt[:200], exc
                )
                raise RuntimeError(
                    f"Schema bootstrap failed on statement:\n{stmt[:200]}\n{exc}"
                ) from exc

        logger.info("DuckDB DDL complete — verifying required objects...")

        # -----------------------------------------------------------------------
        # Required-object assertion
        # Checks both tables (pipeline_runs) and views.
        # -----------------------------------------------------------------------
        registered = {
            row[0].lower()
            for row in con.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }
        missing = {obj for obj in REQUIRED_OBJECTS if obj.lower() not in registered}
        if missing:
            raise RuntimeError(
                f"Schema bootstrap incomplete — missing objects: {sorted(missing)}\n"
                "Check schema.sql for CREATE statement errors."
            )

        logger.info("DuckDB initialized at %s", cfg.DB_PATH)
        logger.info("All %d required objects verified.", len(REQUIRED_OBJECTS))

        views = [r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_type = 'VIEW'"
        ).fetchall()]
        logger.info("Registered views (%d): %s", len(views), sorted(views))

    finally:
        con.close()


# ---------------------------------------------------------------------------
# Parquet path substitution map
# Kept here (not in schema.sql) — schema.sql uses the placeholder pattern.
# PARQUET_MAP is used by load.py files to know where to write parquets and
# by tests to construct fixture paths.
# ---------------------------------------------------------------------------

PARQUET_MAP: dict[str, Path] = {
    "PSX_PARQUET":               cfg.PSX_PROCESSED_DIR / "psx_prices.parquet",
    "BSP_PARQUET":               cfg.BSP_PROCESSED_DIR / "bsp_policy_rate.parquet",
    "FX_PARQUET":                cfg.FX_PROCESSED_DIR  / "fx_rates.parquet",
    "ECONOMIC_CPI_PARQUET":      cfg.DATA_PROCESSED / "economic" / "cpi_trend.parquet",
    "ECONOMIC_GDP_PARQUET":      cfg.DATA_PROCESSED / "economic" / "gdp_tracker.parquet",
    "ECONOMIC_REMITTANCE_PARQUET": cfg.DATA_PROCESSED / "economic" / "remittance_trend.parquet",
    "ECONOMIC_DASHBOARD_PARQUET": cfg.DATA_PROCESSED / "economic" / "economic_dashboard.parquet",
    # PATCH FINDING-005: GDP_PARQUET, CPI_PARQUET, REMITTANCE_PARQUET removed —
    # unused short aliases duplicating ECONOMIC_GDP/CPI/REMITTANCE_PARQUET keys.
    "LABOR_PARQUET":             cfg.DATA_PROCESSED / "labor"    / "labor_market.parquet",
    "REGIONAL_PARQUET":          cfg.DATA_PROCESSED / "regional" / "regional_inequality.parquet",
    "COMMODITY_PARQUET":         cfg.DATA_PROCESSED / "prices"   / "commodity_prices.parquet",
    "FOOD_PARQUET":              cfg.DATA_PROCESSED / "prices"   / "food_price_decomposition.parquet",
    "SENTIMENT_PARQUET":         cfg.DATA_PROCESSED / "sentiment"/ "social_sentiment.parquet",
    "COA_PARQUET":               cfg.DATA_PROCESSED / "coa"      / "coa_budget_utilization.parquet",
}


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    try:
        init_db()
    except RuntimeError as exc:
        logger.error("Init failed: %s", exc)
        sys.exit(1)
    sys.exit(0)