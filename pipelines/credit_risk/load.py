"""
credit_risk/load.py
===================
Write transformed DataFrame to Parquet and register DuckDB view.

Uses cfg.DB_PATH for DuckDB connection (db/duckdb_local.db).
Uses cfg.ENRICHMENT_PROCESSED_DIR for Parquet output.

Idempotency:
  - Parquet write overwrites previous file (safe re-run).
  - CREATE OR REPLACE VIEW is idempotent.
  - Both operations are independent — Parquet write failure does not corrupt DuckDB.
"""
from __future__ import annotations

import logging

import duckdb
import pandas as pd

import config as cfg

logger = logging.getLogger(__name__)

_PARQUET_PATH = cfg.ENRICHMENT_PROCESSED_DIR / "credit_exposure.parquet"


def load(df: pd.DataFrame) -> None:
    """
    Write DataFrame to Parquet and register credit_exposure DuckDB view.

    Args:
        df: Transformed DataFrame from transform.py.
            May be empty (zero rows) — view will register but return no rows.
    """
    cfg.ENRICHMENT_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Write Parquet (idempotent) ────────────────────────────────
    df.to_parquet(_PARQUET_PATH, index=False)
    logger.info(
        "[credit_risk] Wrote %d row(s) to %s",
        len(df), _PARQUET_PATH,
    )

    # ── Step 2: Register DuckDB view (idempotent via CREATE OR REPLACE) ──
    # Uses cfg.DB_PATH (db/duckdb_local.db) — the canonical R1 database path.
    # Opens a read-write connection for the duration of the view registration
    # only. This is safe because load.py is called from a pipeline scheduler
    # context (APScheduler / cron), never from a concurrent API request context.
    try:
        with duckdb.connect(str(cfg.DB_PATH)) as con:
            con.execute(f"""
                CREATE OR REPLACE VIEW credit_exposure AS
                SELECT * FROM read_parquet('{_PARQUET_PATH}')
            """)
        logger.info("[credit_risk] DuckDB view 'credit_exposure' registered.")
    except Exception as exc:
        # View registration failure is non-fatal — Parquet is already written.
        # Next successful run will re-register the view.
        logger.error(
            "[credit_risk] DuckDB view registration failed: %s. "
            "Parquet is intact — re-run will recover.",
            exc,
        )
        raise
