"""
BSP pipeline entry point.

Orchestrates: extract → transform → load

Can be invoked three ways:
  1. Direct import:    from pipelines.bsp.run import run; run()
  2. Module execution: python -m pipelines.bsp.run
  3. APScheduler:      scheduler calls run() via importlib (cron, day=1, hour=8)

E2E smoke (run after Phase 0.5 gates pass and Phase 2 first run completes):

  Row count + date range:
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    r = con.execute('SELECT COUNT(*), MIN(decision_date), MAX(decision_date) FROM bsp_policy_rate').fetchone()
    print(f'rows={r[0]}, from={r[1]}, to={r[2]}')
    con.close()
    "
    → expect: ~70-120 rows, from ~2002 or 2010 (cfg.BSP_START_YEAR), to current year

  Direction spot-check (June 2023 = 6.25 → hike, Oct 2023 = 6.25 → hold):
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    rows = con.execute(
        'SELECT decision_date, overnight_rp, direction FROM bsp_policy_rate '
        'WHERE YEAR(decision_date) = 2023 ORDER BY decision_date'
    ).fetchall()
    for r in rows: print(r)
    con.close()
    "
    → expect: May 2023 (6.25, hike), Aug 2023 (6.25, hold), Nov 2023 (6.50, hike)
      (exact dates and rates depend on BSP page at run time)

  Cross-join check (confirms psx_vs_bsp ASOF JOIN is working):
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    r = con.execute('SELECT COUNT(*) FROM psx_vs_bsp WHERE rate_direction IS NOT NULL').fetchone()
    print(f'psx_vs_bsp with direction: {r[0]}')
    con.close()
    "
    → expect: non-zero — should match or exceed psx_prices row count

  pipeline_runs check:
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    rows = con.execute(
        'SELECT * FROM pipeline_runs WHERE pipeline = \\'bsp\\' ORDER BY run_at DESC LIMIT 5'
    ).fetchall()
    for r in rows: print(r)
    con.close()
    "
    → expect: at least one ('bsp', 'success', N) row
"""

from __future__ import annotations

import logging
import sys

from pipelines.bsp.extract   import extract
from pipelines.bsp.transform import transform
from pipelines.bsp.load      import load

logger = logging.getLogger(__name__)


def run() -> None:
    logger.info("=== BSP pipeline start ===")
    try:
        extract()
        transform()
        load()
        logger.info("=== BSP pipeline complete ===")
    except Exception as exc:
        logger.error("=== BSP pipeline FAILED: %s ===", exc)
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