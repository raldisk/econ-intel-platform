"""
Prices pipeline entry point.

Orchestrates: extract → transform → load

Scheduled: interval every 6 hours (APScheduler, cfg.SCHEDULE prices_interval).
Also invocable as CLI: python -m pipelines.prices.run

E2E smoke:

  Commodity price check:
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    r = con.execute(
        'SELECT COUNT(*), COUNT(DISTINCT commodity_slug), '
        'MIN(price_date), MAX(price_date) FROM commodity_prices'
    ).fetchone()
    print(f'rows={r[0]}, commodities={r[1]}, from={r[2]}, to={r[3]}')
    con.close()
    "
    → expect: 1000+ rows, 12-15 commodities, from 2000-01-01 onwards

  STL decomposition check:
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    rows = con.execute(
        'SELECT commodity_slug, COUNT(*) as n FROM food_price_decomposition '
        'GROUP BY 1 ORDER BY 1 LIMIT 10'
    ).fetchall()
    for r in rows: print(r)
    con.close()
    "
    → expect: 10-12 commodities, each with 200+ decomp rows

  Price shock check:
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    r = con.execute(
        'SELECT commodity_slug, period, z_score, shock_direction '
        'FROM price_shock_events WHERE is_shock = TRUE '
        'ORDER BY ABS(z_score) DESC LIMIT 5'
    ).fetchall()
    for row in r: print(row)
    con.close()
    "
    → expect: onion_white/onion_red at top (2023 spike)

  Synthetic source check:
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    rows = con.execute('SELECT source, COUNT(*) FROM commodity_prices GROUP BY 1').fetchall()
    for r in rows: print(r)
    con.close()
    "
    → SYNTHETIC_FALLBACK if no real CSVs; PSA_SITUATIONER if real
"""

from __future__ import annotations

import logging
import sys

from pipelines.prices.extract   import extract
from pipelines.prices.transform import transform
from pipelines.prices.load      import load

logger = logging.getLogger(__name__)


def run() -> None:
    logger.info("=== Prices pipeline start ===")
    try:
        extract()
        transform()
        load()
        logger.info("=== Prices pipeline complete ===")
    except Exception as exc:
        logger.error("=== Prices pipeline FAILED: %s ===", exc)
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