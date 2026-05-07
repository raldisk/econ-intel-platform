"""
BSP load — registers the processed parquet as a DuckDB view.

Replaces the bsp_policy_rate placeholder stub written by db/schema.sql at init time.
Logs outcome to pipeline_runs.

Interface contract:
    load() -> None   writes view, raises on failure

Pattern: mirrors pipelines/psx/load.py exactly — same connection helpers,
same pipeline_runs log pattern, same nested try/except structure.
"""

from __future__ import annotations

import logging

from db.init import PARQUET_MAP
from lib.db import get_write_conn

logger = logging.getLogger(__name__)

_PIPELINE_NAME = "bsp"
_VIEW_NAME     = "bsp_policy_rate"


def load() -> None:
    """
    Register bsp_policy_rate as a DuckDB view over the processed parquet.
    Replaces the placeholder stub from schema.sql on first successful run.
    Subsequent runs refresh the view (idempotent — CREATE OR REPLACE).
    Logs a pipeline_runs record on both success and failure.
    """
    parquet_path = PARQUET_MAP["BSP_PARQUET"]

    if not parquet_path.exists():
        _log_run(status="error", rows=0,
                 error_msg=f"Parquet not found: {parquet_path}")
        raise FileNotFoundError(
            f"BSP parquet not found at {parquet_path} — run transform() first."
        )

    view_sql = (
        f"CREATE OR REPLACE VIEW {_VIEW_NAME} AS "
        f"SELECT * FROM read_parquet('{parquet_path.as_posix()}')"
    )

    try:
        with get_write_conn() as con:
            con.execute(view_sql)

            result = con.execute(
                f"SELECT COUNT(*), MIN(decision_date), MAX(decision_date) "
                f"FROM {_VIEW_NAME}"
            ).fetchone()
            row_count = result[0]

            logger.info(
                "bsp_policy_rate registered: %d decisions | %s → %s",
                row_count, result[1], result[2],
            )

            _log_run_in_conn(con, status="success", rows=row_count)

    except Exception as exc:
        _log_run(status="error", rows=0, error_msg=str(exc))
        raise


# ---------------------------------------------------------------------------
# pipeline_runs helpers — mirrors psx/load.py exactly
# ---------------------------------------------------------------------------

def _log_run_in_conn(
    con,
    *,
    status: str,
    rows: int,
    error_msg: str | None = None,
) -> None:
    """
    Insert pipeline run record using an already-open write connection.
    Wrapped in its own try/except — a failed log must not mask the real error.
    """
    try:
        con.execute(
            "INSERT INTO pipeline_runs (pipeline, status, rows_affected, error_msg) "
            "VALUES (?, ?, ?, ?)",
            [_PIPELINE_NAME, status, rows, error_msg],
        )
    except Exception as log_exc:
        logger.debug(
            "Could not write to pipeline_runs (%s) — non-fatal: %s",
            status, log_exc,
        )


def _log_run(
    *,
    status: str,
    rows: int,
    error_msg: str | None = None,
) -> None:
    """
    Open a fresh write connection solely to log a run record.
    Used when the main connection was never opened (parquet missing path).
    """
    try:
        with get_write_conn() as con:
            _log_run_in_conn(con, status=status, rows=rows, error_msg=error_msg)
    except Exception as log_exc:
        logger.debug("pipeline_runs log failed (non-fatal): %s", log_exc)