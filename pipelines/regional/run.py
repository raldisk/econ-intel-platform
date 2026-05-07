"""
Regional pipeline entry point.

Orchestrates: extract → transform → load

DATA SOURCE:
  Uses synthetic PSA-anchored FIES data by default.
  To use real data, set cfg.REGIONAL_DATA_DIR and provide:
    fies_2021.csv, fies_2023.csv, poverty_provincial.csv

E2E smoke commands:

  Row count + year/region coverage:
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    r = con.execute(
        'SELECT COUNT(*), MIN(survey_year), MAX(survey_year), '
        'COUNT(DISTINCT region) FROM regional_inequality'
    ).fetchone()
    print(f'rows={r[0]}, years={r[1]}-{r[2]}, regions={r[3]}')
    con.close()
    "
    → expect: rows=34, years=2021-2023, regions=17

  Gini spot-check (BARMM highest, NCR lowest):
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    rows = con.execute(
        'SELECT region, survey_year, gini_coefficient, mean_income '
        'FROM regional_inequality '
        'ORDER BY survey_year DESC, gini_coefficient DESC'
    ).fetchall()
    for r in rows[:5]: print(r)
    con.close()
    "
    → expect: BARMM near top (highest Gini), NCR near bottom

  Quintile share validation (Q1+Q2+Q3+Q4+Q5 should sum to ~100):
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    rows = con.execute(
        'SELECT region, survey_year, '
        'ROUND(income_share_q1+income_share_q2+income_share_q3+'
        'income_share_q4+income_share_q5, 1) AS total_share '
        'FROM regional_inequality LIMIT 5'
    ).fetchall()
    for r in rows: print(r)
    con.close()
    "
    → expect: total_share ~100.0 for all rows

  pipeline_runs check:
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    rows = con.execute(
        'SELECT pipeline, status, rows_affected, run_at '
        'FROM pipeline_runs WHERE pipeline = chr(114)||chr(101)||chr(103)||chr(105)||chr(111)||chr(110)||chr(97)||chr(108) '
        'ORDER BY run_at DESC LIMIT 5'
    ).fetchall()
    for r in rows: print(r)
    con.close()
    "
    → expect: ('regional', 'success', 34, ...)
"""

from __future__ import annotations

import logging
import sys

from pipelines.regional.extract   import extract
from pipelines.regional.transform import transform
from pipelines.regional.load      import load

logger = logging.getLogger(__name__)


def run() -> None:
    logger.info("=== Regional pipeline start ===")
    try:
        extract()
        transform()
        load()
        logger.info("=== Regional pipeline complete ===")
    except Exception as exc:
        logger.error("=== Regional pipeline FAILED: %s ===", exc)
        raise


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    try:
        run()
    except Exception:
        sys.exit(1)
    sys.exit(0)