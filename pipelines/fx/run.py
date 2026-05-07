"""
FX pipeline entry point.

Orchestrates: extract → transform → load

Invocation:
  1. Direct import:    from pipelines.fx.run import run; run()
  2. Module execution: python -m pipelines.fx.run
  3. APScheduler:      {"pipeline": "fx", "trigger": "cron", "hour": 9, "minute": 0}

E2E smoke (run after Phase 0.5 gates and BSP pipeline both pass):

  Row count + date range:
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    r = con.execute(
        'SELECT COUNT(*), MIN(rate_date), MAX(rate_date) FROM fx_rates '
        'WHERE currency_pair = chr(85)||chr(83)||chr(68)||chr(47)||chr(80)||chr(72)||chr(80)'
    ).fetchone()
    print(f'USD/PHP rows={r[0]}, from={r[1]}, to={r[2]}')
    con.close()
    "
    → expect: 100+ rows, from ~FX_START_YEAR-01-01, to current year

  Forward-fill check (stg_fx_rates should have no gaps for weekdays):
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    r = con.execute(
        'SELECT COUNT(*) FROM stg_fx_rates WHERE rate IS NULL'
    ).fetchone()
    print(f'null rate rows in stg_fx_rates: {r[0]}')
    con.close()
    "
    → expect: 0

  Volatility check:
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    r = con.execute(
        'SELECT vol_regime, COUNT(*) FROM fx_volatility GROUP BY 1 ORDER BY 1'
    ).fetchall()
    for row in r: print(row)
    con.close()
    "
    → expect: distribution across 'low', 'moderate', 'high' regimes

  Cross rates check:
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    r = con.execute(
        'SELECT DISTINCT currency_pair FROM fx_rates ORDER BY 1'
    ).fetchall()
    print([row[0] for row in r])
    con.close()
    "
    → expect: ['AUD/PHP', 'CAD/PHP', 'CNY/PHP', 'EUR/PHP', 'GBP/PHP',
               'HKD/PHP', 'JPY/PHP', 'SGD/PHP', 'USD/PHP']

  pipeline_runs check:
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    rows = con.execute(
        'SELECT pipeline, status, rows_affected, run_at '
        'FROM pipeline_runs WHERE pipeline = chr(102)||chr(120) '
        'ORDER BY run_at DESC LIMIT 5'
    ).fetchall()
    for r in rows: print(r)
    con.close()
    "
    → expect: at least one ('fx', 'success', N) row
"""

from __future__ import annotations

import logging
import sys

from pipelines.fx.extract   import extract
from pipelines.fx.transform import transform
from pipelines.fx.load      import load

logger = logging.getLogger(__name__)


def run() -> None:
    logger.info("=== FX pipeline start ===")
    try:
        extract()
        transform()
        load()
        logger.info("=== FX pipeline complete ===")
    except Exception as exc:
        logger.error("=== FX pipeline FAILED: %s ===", exc)
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