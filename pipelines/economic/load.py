"""
Economic load — registers DuckDB views for all four economic mart parquets.

Views created:
  cpi_trend            — monthly CPI index, inflation, MoM change
  gdp_tracker          — annual GDP series, YoY growth, per-capita
  remittance_trend     — annual OFW remittances, YoY growth, 3yr rolling avg
  economic_dashboard   — wide annual join for Streamlit summary cards

Cross-pipeline dependency:
  real_exchange_rate (created in fx/load.py) references cpi_trend.
  No action needed here — DuckDB views evaluate lazily.
  Run fx/load.py after economic/load.py to activate real_exchange_rate.

Interface contract:
    load() -> None
    Raises on missing parquet or DDL failure.
    Logs to pipeline_runs on both success and failure.
"""

from __future__ import annotations

import logging

from db.init import PARQUET_MAP
from lib.db import get_write_conn

logger = logging.getLogger(__name__)

_PIPELINE = "economic"

_VIEWS: list[tuple[str, str]] = [
    ("cpi_trend",          "ECONOMIC_CPI_PARQUET"),
    ("gdp_tracker",        "ECONOMIC_GDP_PARQUET"),
    ("remittance_trend",   "ECONOMIC_REMITTANCE_PARQUET"),
    ("economic_dashboard", "ECONOMIC_DASHBOARD_PARQUET"),
]


def load() -> None:
    """
    Register all four economic mart views in DuckDB.
    Counts total rows across cpi_trend + gdp_tracker as the primary health check.
    Logs outcome to pipeline_runs.
    """
    # Preflight: all four parquets must exist
    for view_name, map_key in _VIEWS:
        parquet_path = PARQUET_MAP[map_key]
        if not parquet_path.exists():
            _log_run(status="error", rows=0,
                     error_msg=f"{map_key} parquet not found: {parquet_path}")
            raise FileNotFoundError(
                f"Economic parquet not found at {parquet_path} — "
                f"run transform() first."
            )

    try:
        with get_write_conn() as con:
            for view_name, map_key in _VIEWS:
                parquet_path = PARQUET_MAP[map_key]
                con.execute(
                    f"CREATE OR REPLACE VIEW {view_name} AS "
                    f"SELECT * FROM read_parquet('{parquet_path.as_posix()}')"
                )
                logger.info("View registered: %s", view_name)

            # Health check — spot count on two core marts
            cpi_rows = con.execute(
                "SELECT COUNT(*) FROM cpi_trend"
            ).fetchone()[0]
            gdp_rows = con.execute(
                "SELECT COUNT(*), MIN(period_year), MAX(period_year) "
                "FROM gdp_tracker"
            ).fetchone()

            logger.info(
                "Economic load complete: cpi_trend=%d rows | "
                "gdp_tracker=%d rows [%s → %s]",
                cpi_rows, gdp_rows[0], gdp_rows[1], gdp_rows[2],
            )

            _log_run_in_conn(con, status="success", rows=cpi_rows + gdp_rows[0])

    except Exception as exc:
        _log_run(status="error", rows=0, error_msg=str(exc))
        raise


# ---------------------------------------------------------------------------
# pipeline_runs helpers — mirrors fx/load.py and bsp/load.py
# ---------------------------------------------------------------------------

def _log_run_in_conn(con, *, status: str, rows: int,
                     error_msg: str | None = None) -> None:
    try:
        con.execute(
            "INSERT INTO pipeline_runs "
            "(pipeline, status, rows_affected, error_msg) VALUES (?, ?, ?, ?)",
            [_PIPELINE, status, rows, error_msg],
        )
    except Exception as log_exc:
        logger.debug("pipeline_runs log failed (non-fatal): %s", log_exc)


def _log_run(*, status: str, rows: int,
             error_msg: str | None = None) -> None:
    try:
        with get_write_conn() as con:
            _log_run_in_conn(con, status=status, rows=rows, error_msg=error_msg)
    except Exception as log_exc:
        logger.debug("pipeline_runs log failed (non-fatal): %s", log_exc)
