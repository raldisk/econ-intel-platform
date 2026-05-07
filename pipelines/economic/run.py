"""
Economic pipeline entry point.

Orchestrates: extract → transform → load

Sources:
  PSA OpenSTAT API    — monthly CPI All Items + CPI YoY
  World Bank API      — annual GDP, inflation, unemployment, remittances
  BSP CSV (optional)  — monthly remittance totals (cfg.BSP_REMITTANCE_CSV)

Static pipeline — not scheduled. Run manually after each quarterly PSA release:
  python -m pipelines.economic.run

E2E smoke (run after Phase 0.5 gates + FX pipeline E2E both pass):

  Row count + date range for CPI:
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    r = con.execute(
        'SELECT COUNT(*), MIN(period_date), MAX(period_date) FROM cpi_trend'
    ).fetchone()
    print(f'cpi_trend rows={r[0]}, from={r[1]}, to={r[2]}')
    con.close()
    "
    → expect: 60–200 rows, period_date spanning several years

  GDP tracker:
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    rows = con.execute(
        'SELECT period_year, gdp_usd_bn, gdp_growth_pct '
        'FROM gdp_tracker ORDER BY period_year DESC LIMIT 5'
    ).fetchall()
    for r in rows: print(r)
    con.close()
    "
    → expect: recent years with non-null gdp_usd_bn and gdp_growth_pct

  Economic dashboard:
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    r = con.execute(
        'SELECT COUNT(*), MIN(period_year), MAX(period_year) FROM economic_dashboard'
    ).fetchone()
    print(f'dashboard rows={r[0]}, from={r[1]}, to={r[2]}')
    con.close()
    "
    → expect: rows spanning 1990s to present

  real_exchange_rate (cross-pipeline — requires fx loaded first):
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    r = con.execute(
        'SELECT COUNT(*) FROM real_exchange_rate WHERE real_rate IS NOT NULL'
    ).fetchone()
    print(f'real_exchange_rate non-null real_rate: {r[0]}')
    con.close()
    "
    → expect: non-zero (requires both fx_rates and cpi_trend to be populated)

  pipeline_runs check:
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    rows = con.execute(
        'SELECT pipeline, status, rows_affected, run_at '
        'FROM pipeline_runs WHERE pipeline = chr(101)||chr(99)||chr(111)||chr(110)||chr(111)||chr(109)||chr(105)||chr(99) '
        'ORDER BY run_at DESC LIMIT 3'
    ).fetchall()
    for r in rows: print(r)
    con.close()
    "
    → expect: ('economic', 'success', N, timestamp)
"""

from __future__ import annotations

import logging
import sys

from pipelines.economic.extract   import extract
from pipelines.economic.transform import transform
from pipelines.economic.load      import load

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


def run() -> None:
    logger.info("Economic pipeline starting: extract → transform → load")
    try:
        extract()
        transform()
        load()
        logger.info("Economic pipeline complete.")
    except Exception as exc:
        logger.error("Economic pipeline failed: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    run()
