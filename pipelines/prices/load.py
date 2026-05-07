"""
Prices load — registers commodity_prices and food_price_decomposition DuckDB views
plus derived analysis views ported from PH-Food-Price-Decomposition SQL files.

Views created:
  commodity_prices            — base view over commodity_prices.parquet
  food_price_decomposition    — base view over food_price_decomposition.parquet
  price_trend_by_commodity    — monthly price trend with MoM/YoY change
  seasonal_price_index        — seasonal index per commodity per month
  price_shock_events          — months where price deviates >2 std from trend

Interface contract:
    load() -> None
    Raises on failure; logs to pipeline_runs.
"""

from __future__ import annotations

import logging

from db.init import PARQUET_MAP
from lib.db import get_write_conn

logger = logging.getLogger(__name__)

_PIPELINE = "prices"

# ---------------------------------------------------------------------------
# Derived view SQL — ported from PH-Food-Price-Decomposition/sql/
# ---------------------------------------------------------------------------

# price_trend_by_commodity: monthly price with MoM and YoY pct change
_PRICE_TREND_SQL = """
CREATE OR REPLACE VIEW price_trend_by_commodity AS
WITH monthly AS (
    SELECT
        price_date,
        commodity_slug,
        commodity,
        unit,
        ROUND(AVG(retail_price_php)::NUMERIC, 2) AS avg_price,
        source
    FROM commodity_prices
    WHERE region = 'National'
    GROUP BY price_date, commodity_slug, commodity, unit, source
)
SELECT
    price_date,
    commodity_slug,
    commodity,
    unit,
    avg_price,
    source,
    ROUND(
        (avg_price - LAG(avg_price) OVER (
            PARTITION BY commodity_slug ORDER BY price_date
        )) / NULLIF(LAG(avg_price) OVER (
            PARTITION BY commodity_slug ORDER BY price_date
        ), 0) * 100,
    4) AS mom_pct_change,
    ROUND(
        (avg_price - LAG(avg_price, 12) OVER (
            PARTITION BY commodity_slug ORDER BY price_date
        )) / NULLIF(LAG(avg_price, 12) OVER (
            PARTITION BY commodity_slug ORDER BY price_date
        ), 0) * 100,
    4) AS yoy_pct_change
FROM monthly
ORDER BY commodity_slug, price_date
"""

# seasonal_price_index: ratio of monthly price to 12-month centered moving average
# Ported from PH-Food-Price-Decomposition/sql/seasonal_index.sql
_SEASONAL_INDEX_SQL = """
CREATE OR REPLACE VIEW seasonal_price_index AS
WITH monthly AS (
    SELECT
        DATE_TRUNC('month', price_date)::DATE AS month,
        commodity_slug,
        AVG(retail_price_php)                 AS avg_price
    FROM commodity_prices
    WHERE region = 'National'
    GROUP BY 1, 2
),
cma AS (
    SELECT
        month,
        commodity_slug,
        avg_price,
        AVG(avg_price) OVER (
            PARTITION BY commodity_slug
            ORDER BY month
            ROWS BETWEEN 5 PRECEDING AND 6 FOLLOWING
        ) AS centered_ma_12
    FROM monthly
)
SELECT
    month,
    commodity_slug,
    ROUND(avg_price::NUMERIC, 2)                      AS avg_price,
    ROUND(centered_ma_12::NUMERIC, 2)                 AS centered_ma_12,
    CASE WHEN centered_ma_12 > 0
         THEN ROUND((avg_price / centered_ma_12)::NUMERIC, 4)
    END                                               AS seasonal_index,
    EXTRACT(MONTH FROM month)::INT                    AS month_num,
    CASE WHEN avg_price / NULLIF(centered_ma_12, 0) > 1.05
         THEN TRUE ELSE FALSE END                     AS is_seasonal_high,
    CASE WHEN avg_price / NULLIF(centered_ma_12, 0) < 0.95
         THEN TRUE ELSE FALSE END                     AS is_seasonal_low
FROM cma
WHERE centered_ma_12 IS NOT NULL
ORDER BY commodity_slug, month
"""

# price_shock_events: months where |residual| > 2 std of commodity residuals
# Uses STL residual from food_price_decomposition
_SHOCK_EVENTS_SQL = """
CREATE OR REPLACE VIEW price_shock_events AS
WITH stats AS (
    SELECT
        commodity_slug,
        AVG(residual)    AS mean_resid,
        STDDEV(residual) AS std_resid
    FROM food_price_decomposition
    GROUP BY commodity_slug
)
SELECT
    f.period,
    f.commodity_slug,
    ROUND(f.observed::NUMERIC,  2) AS observed_price,
    ROUND(f.trend::NUMERIC,     2) AS trend_price,
    ROUND(f.seasonal::NUMERIC,  4) AS seasonal_component,
    ROUND(f.residual::NUMERIC,  4) AS residual,
    ROUND(
        (f.residual - s.mean_resid) / NULLIF(s.std_resid, 0),
    4) AS z_score,
    CASE
        WHEN ABS((f.residual - s.mean_resid) / NULLIF(s.std_resid, 0)) > 2
        THEN TRUE ELSE FALSE
    END AS is_shock,
    CASE
        WHEN f.residual > s.mean_resid + 2 * s.std_resid THEN 'positive_shock'
        WHEN f.residual < s.mean_resid - 2 * s.std_resid THEN 'negative_shock'
        ELSE 'normal'
    END AS shock_direction
FROM food_price_decomposition f
JOIN stats s ON f.commodity_slug = s.commodity_slug
ORDER BY f.commodity_slug, f.period
"""


# ---------------------------------------------------------------------------
# load()
# ---------------------------------------------------------------------------

def load() -> None:
    commodity_path = PARQUET_MAP["COMMODITY_PARQUET"]
    food_path      = PARQUET_MAP["FOOD_PARQUET"]

    missing = [str(p) for p in (commodity_path, food_path) if not p.exists()]
    if missing:
        msg = f"Prices parquet(s) not found: {missing} — run transform() first."
        _log_run(status="error", rows=0, error_msg=msg)
        raise FileNotFoundError(msg)

    def _base_view(name: str, path) -> str:
        return (f"CREATE OR REPLACE VIEW {name} AS "
                f"SELECT * FROM read_parquet('{path.as_posix()}')")

    try:
        with get_write_conn() as con:
            con.execute(_base_view("commodity_prices",         commodity_path))
            con.execute(_base_view("food_price_decomposition", food_path))

            commodity_rows = con.execute("SELECT COUNT(*) FROM commodity_prices").fetchone()[0]
            food_rows      = con.execute("SELECT COUNT(*) FROM food_price_decomposition").fetchone()[0]

            logger.info(
                "Prices views registered: commodity_prices=%d rows | "
                "food_price_decomposition=%d rows",
                commodity_rows, food_rows,
            )

            for label, sql in [
                ("price_trend_by_commodity", _PRICE_TREND_SQL),
                ("seasonal_price_index",     _SEASONAL_INDEX_SQL),
                ("price_shock_events",       _SHOCK_EVENTS_SQL),
            ]:
                try:
                    con.execute(sql)
                    logger.info("Prices view created: %s", label)
                except Exception as view_exc:
                    logger.warning("Prices view %s failed (non-fatal): %s",
                                   label, view_exc)

            _log_run_in_conn(con, status="success",
                             rows=commodity_rows + food_rows)

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