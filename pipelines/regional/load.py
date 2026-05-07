"""
Regional load — registers the regional_inequality DuckDB view.

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

_PIPELINE = "regional"
_VIEW_NAME = "regional_inequality"


def load() -> None:
    """Register regional_inequality as a DuckDB view over the processed parquet."""
    parquet_path = PARQUET_MAP["REGIONAL_PARQUET"]

    if not parquet_path.exists():
        _log_run(status="error", rows=0,
                 error_msg=f"Regional parquet not found: {parquet_path}")
        raise FileNotFoundError(
            f"Regional parquet not found at {parquet_path} — run transform() first."
        )

    view_sql = (
        f"CREATE OR REPLACE VIEW {_VIEW_NAME} AS "
        f"SELECT * FROM read_parquet('{parquet_path.as_posix()}')"
    )

    try:
        with get_write_conn() as con:
            con.execute(view_sql)

            result = con.execute(
                f"SELECT COUNT(*), "
                f"MIN(survey_year), MAX(survey_year), "
                f"COUNT(DISTINCT region), "
                f"AVG(gini_coefficient) "
                f"FROM {_VIEW_NAME}"
            ).fetchone()

            row_count  = result[0]
            year_min   = result[1]
            year_max   = result[2]
            n_regions  = result[3]
            avg_gini   = round(result[4], 4) if result[4] is not None else None

            logger.info(
                "regional_inequality registered: %d rows | years=%s-%s | "
                "%d regions | avg Gini=%.4f",
                row_count, year_min, year_max, n_regions, avg_gini or 0.0,
            )

            # Spot-check BARMM and NCR — the two most extreme regions in PH
            for region_name in ("BARMM", "NCR"):
                spot = con.execute(
                    f"SELECT survey_year, gini_coefficient, mean_income "
                    f"FROM {_VIEW_NAME} "
                    f"WHERE region LIKE '%{region_name}%' "
                    f"ORDER BY survey_year DESC LIMIT 1"
                ).fetchone()
                if spot:
                    logger.info(
                        "  %s (%d): Gini=%.4f, mean_income=PHP%.0f",
                        region_name, spot[0], spot[1] or 0.0, spot[2] or 0.0,
                    )

            _log_run_in_conn(con, status="success", rows=row_count)

    except Exception as exc:
        _log_run(status="error", rows=0, error_msg=str(exc))
        raise


# ---------------------------------------------------------------------------
# pipeline_runs helpers
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