"""
Labor pipeline entry point.

Orchestrates: extract → transform → load

DATA GAP: This pipeline requires a PSA LFS CSV (set cfg.LABOR_LFS_CSV).
Without it, the pipeline completes successfully but labor_market contains
zero rows. The dashboard Labor page shows "No LFS data available."

To enable:
  1. Download PSA LFS data from https://psa.gov.ph/content/labor-force-survey-lfs
  2. Set cfg.LABOR_LFS_CSV = Path("path/to/lfs.csv")
  3. Run: python -m pipelines.labor.run

E2E smoke (after providing real LFS data):

  Row count + survey rounds:
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    r = con.execute(
        'SELECT COUNT(*), COUNT(DISTINCT survey_round), COUNT(DISTINCT region) '
        'FROM labor_market'
    ).fetchone()
    print(f'rows={r[0]}, rounds={r[1]}, regions={r[2]}')
    con.close()
    "
    → expect: rows>0, rounds>=1, regions>=17 (all PH regions)

  Regional unemployment spot-check:
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    rows = con.execute(
        'SELECT survey_round, region, unemployment_rate '
        'FROM labor_market ORDER BY unemployment_rate DESC LIMIT 5'
    ).fetchall()
    for r in rows: print(r)
    con.close()
    "
    → expect: highest unemployment in BARMM or Eastern Visayas per PSA data

  Data gap check (before providing real data):
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    r = con.execute('SELECT COUNT(*) FROM labor_market').fetchone()
    print(f'labor_market rows: {r[0]}')
    con.close()
    "
    → expect: 0 (data gap — pipeline ran but no LFS CSV provided)

  pipeline_runs check:
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    rows = con.execute(
        'SELECT pipeline, status, rows_affected, run_at '
        'FROM pipeline_runs WHERE pipeline = chr(108)||chr(97)||chr(98)||chr(111)||chr(114) '
        'ORDER BY run_at DESC LIMIT 5'
    ).fetchall()
    for r in rows: print(r)
    con.close()
    "
    → expect: ('labor', 'success', 0, ...) when no CSV; ('labor', 'success', N, ...) with CSV
"""

from __future__ import annotations

import logging
import sys

from pipelines.labor.extract   import extract
from pipelines.labor.transform import transform
from pipelines.labor.load      import load

logger = logging.getLogger(__name__)


def run() -> None:
    logger.info("=== Labor pipeline start ===")
    try:
        extract()
        transform()
        load()
        logger.info("=== Labor pipeline complete ===")
    except Exception as exc:
        logger.error("=== Labor pipeline FAILED: %s ===", exc)
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