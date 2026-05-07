"""
COA load — registers coa_budget_utilization DuckDB view and derived views.

Views created:
  coa_budget_utilization   — base view over parquet
  coa_agency_heatmap       — disbursement rate by agency × year (wide pivot)
  coa_low_utilizers        — agencies below threshold, ranked by z-score
  coa_trend_by_agency      — disbursement_rate over time per agency

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

_PIPELINE = "coa"

_HEATMAP_SQL = """
CREATE OR REPLACE VIEW coa_agency_heatmap AS
SELECT
    agency_code,
    agency,
    agency_type,
    fiscal_year,
    ROUND(disbursement_rate::NUMERIC, 2)    AS disbursement_rate,
    ROUND(obligation_rate::NUMERIC, 2)      AS obligation_rate,
    is_low_utilizer,
    is_high_utilizer,
    ROUND(zscore_disbursement::NUMERIC, 4)  AS zscore_disbursement
FROM coa_budget_utilization
ORDER BY agency_code, fiscal_year
"""

_LOW_SQL = """
CREATE OR REPLACE VIEW coa_low_utilizers AS
SELECT
    fiscal_year,
    agency_code,
    agency,
    agency_type,
    ROUND(disbursement_rate::NUMERIC, 2)    AS disbursement_rate,
    ROUND(zscore_disbursement::NUMERIC, 4)  AS zscore_disbursement,
    ROUND(appropriation_php::NUMERIC, 0)    AS appropriation_php,
    source
FROM coa_budget_utilization
WHERE is_low_utilizer = TRUE
ORDER BY fiscal_year DESC, zscore_disbursement ASC
"""

_TREND_SQL = """
CREATE OR REPLACE VIEW coa_trend_by_agency AS
SELECT
    agency_code,
    agency,
    fiscal_year,
    ROUND(disbursement_rate::NUMERIC, 2)    AS disbursement_rate,
    LAG(disbursement_rate) OVER (
        PARTITION BY agency_code ORDER BY fiscal_year
    )                                        AS prev_rate,
    ROUND((disbursement_rate - LAG(disbursement_rate) OVER (
        PARTITION BY agency_code ORDER BY fiscal_year
    ))::NUMERIC, 2)                          AS rate_yoy_change
FROM coa_budget_utilization
ORDER BY agency_code, fiscal_year
"""


def load() -> None:
    parquet_path = PARQUET_MAP["COA_PARQUET"]

    if not parquet_path.exists():
        msg = f"COA parquet not found: {parquet_path} — run transform() first."
        _log_run(status="error", rows=0, error_msg=msg)
        raise FileNotFoundError(msg)

    try:
        with get_write_conn() as con:
            con.execute(
                f"CREATE OR REPLACE VIEW coa_budget_utilization AS "
                f"SELECT * FROM read_parquet('{parquet_path.as_posix()}')"
            )
            row_count = con.execute(
                "SELECT COUNT(*) FROM coa_budget_utilization"
            ).fetchone()[0]

            logger.info(
                "coa_budget_utilization registered: %d rows | %d agencies | years: %s",
                row_count,
                con.execute(
                    "SELECT COUNT(DISTINCT agency_code) FROM coa_budget_utilization"
                ).fetchone()[0],
                con.execute(
                    "SELECT LIST(DISTINCT fiscal_year ORDER BY fiscal_year) "
                    "FROM coa_budget_utilization"
                ).fetchone()[0],
            )

            for label, sql in [
                ("coa_agency_heatmap",  _HEATMAP_SQL),
                ("coa_low_utilizers",   _LOW_SQL),
                ("coa_trend_by_agency", _TREND_SQL),
            ]:
                try:
                    con.execute(sql)
                    logger.info("View created: %s", label)
                except Exception as view_exc:
                    logger.warning("View %s failed (non-fatal): %s", label, view_exc)

            _log_run_in_conn(con, status="success", rows=row_count)

    except Exception as exc:
        _log_run(status="error", rows=0, error_msg=str(exc))
        raise


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


def _log_run(*, status: str, rows: int, error_msg: str | None = None) -> None:
    try:
        with get_write_conn() as con:
            _log_run_in_conn(con, status=status, rows=rows, error_msg=error_msg)
    except Exception as log_exc:
        logger.debug("pipeline_runs log failed (non-fatal): %s", log_exc)
