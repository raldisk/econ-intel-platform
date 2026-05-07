"""
Labor load — registers the labor_market DuckDB view.

Handles both the data-present case (real LFS data) and the data-gap case
(empty parquet with correct schema). Both cases log to pipeline_runs with
status='success' — a zero-row labor_market view is correct behaviour when
PSA LFS data has not been provided.

Interface contract:
    load() -> None
    Raises on file-not-found (transform not run) or DuckDB DDL failure.
"""

from __future__ import annotations

import logging

from db.init import PARQUET_MAP
from lib.db import get_write_conn

logger = logging.getLogger(__name__)

_PIPELINE = "labor"
_VIEW_NAME = "labor_market"


def load() -> None:
    """
    Register labor_market as a DuckDB view over the processed parquet.

    If the parquet is empty (data gap), the view is registered and returns
    zero rows. This is not an error. The dashboard page handles the zero-row
    case with a "No LFS data available" message.
    """
    parquet_path = PARQUET_MAP["LABOR_PARQUET"]

    if not parquet_path.exists():
        _log_run(status="error", rows=0,
                 error_msg=f"Labor parquet not found: {parquet_path}")
        raise FileNotFoundError(
            f"Labor parquet not found at {parquet_path} — run transform() first."
        )

    view_sql = (
        f"CREATE OR REPLACE VIEW {_VIEW_NAME} AS "
        f"SELECT * FROM read_parquet('{parquet_path.as_posix()}')"
    )

    try:
        with get_write_conn() as con:
            con.execute(view_sql)
            result = con.execute(
                f"SELECT COUNT(*) FROM {_VIEW_NAME}"
            ).fetchone()
            row_count = result[0]

            if row_count == 0:
                logger.warning(
                    "labor_market registered with 0 rows — PSA LFS data not yet provided. "
                    "Set cfg.LABOR_LFS_CSV and re-run to populate."
                )
            else:
                rounds = con.execute(
                    f"SELECT COUNT(DISTINCT survey_round) FROM {_VIEW_NAME}"
                ).fetchone()[0]
                regions = con.execute(
                    f"SELECT COUNT(DISTINCT region) FROM {_VIEW_NAME}"
                ).fetchone()[0]
                logger.info(
                    "labor_market registered: %d rows | %d survey rounds | %d regions → %s",
                    row_count, rounds, regions, parquet_path,
                )

            _log_run_in_conn(con, status="success", rows=row_count)

    except Exception as exc:
        _log_run(status="error", rows=0, error_msg=str(exc))
        raise


# ---------------------------------------------------------------------------
# pipeline_runs helpers — standard pattern across all load.py modules
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