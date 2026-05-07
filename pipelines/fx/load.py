"""
FX load — registers fx_rates DuckDB view and creates derived mart views.

Views created:
  fx_rates            — base view over fx_rates.parquet (raw daily + cross)
  stg_fx_rates        — forward-filled daily USD/PHP (ported from stg_fx_rates.sql)
  fx_volatility       — 30d/7d rolling std dev + annualized vol (fx_volatility.sql)
  real_exchange_rate  — nominal/real USD/PHP adjusted for CPI (cross-pipeline view)

Cross-pipeline note (real_exchange_rate):
  Depends on cpi_trend from the economic pipeline.
  Created here unconditionally — returns empty until cpi_trend is populated.
  No special handling needed: DuckDB views evaluate lazily.

Interface contract:
    load() -> None
    Raises on failure; logs to pipeline_runs.
"""

from __future__ import annotations

import logging

from db.init import PARQUET_MAP
from lib.db import get_write_conn

logger = logging.getLogger(__name__)

_PIPELINE = "fx"

# ---------------------------------------------------------------------------
# DuckDB SQL for derived views — ported from dbt models (DuckDB-compatible)
# ---------------------------------------------------------------------------

# stg_fx_rates: deduplicate + forward-fill weekend/holiday gaps for USD/PHP.
# DuckDB LAST_VALUE(col IGNORE NULLS) syntax — supported in DuckDB >= 0.10.
# Date spine uses generate_series() which produces TIMESTAMP values; cast to DATE.
# CF-V7-003 fix: stg_fx_rates is self-contained — references fx_rates directly.
_STG_FX_RATES_SQL = """
CREATE OR REPLACE VIEW stg_fx_rates AS
WITH deduped AS (
    SELECT
        rate_date,
        currency_pair,
        rate,
        source,
        ROW_NUMBER() OVER (
            PARTITION BY rate_date, currency_pair
            ORDER BY rate_date DESC
        ) AS rn
    FROM fx_rates
    WHERE rate IS NOT NULL AND rate > 0
),
clean AS (
    SELECT rate_date, currency_pair, rate, source
    FROM deduped WHERE rn = 1
),
usdphp AS (
    SELECT rate_date, rate, source
    FROM clean
    WHERE currency_pair = 'USD/PHP'
),
date_spine AS (
    SELECT unnest(
        generate_series(
            (SELECT MIN(rate_date) FROM usdphp)::TIMESTAMP,
            CURRENT_DATE::TIMESTAMP,
            INTERVAL '1 day'
        )
    )::DATE AS rate_date
),
joined AS (
    SELECT
        ds.rate_date,
        u.rate,
        u.source
    FROM date_spine ds
    LEFT JOIN usdphp u ON ds.rate_date = u.rate_date
),
forward_filled AS (
    SELECT
        rate_date,
        LAST_VALUE(rate  IGNORE NULLS) OVER (
            ORDER BY rate_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS rate,
        LAST_VALUE(source IGNORE NULLS) OVER (
            ORDER BY rate_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS raw_source
    FROM joined
)
SELECT
    rate_date,
    'USD/PHP'                              AS currency_pair,
    rate,
    COALESCE(raw_source, 'forward_fill')   AS source
FROM forward_filled
WHERE rate IS NOT NULL
ORDER BY rate_date
"""

# fx_volatility: 30d/7d rolling std dev + annualized volatility.
# STDDEV_POP, LN, SQRT: all natively supported in DuckDB.
_FX_VOLATILITY_SQL = """
CREATE OR REPLACE VIEW fx_volatility AS
WITH daily AS (
    SELECT rate_date, rate FROM stg_fx_rates
),
with_vol AS (
    SELECT
        rate_date,
        rate,
        STDDEV_POP(rate) OVER (
            ORDER BY rate_date
            ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
        ) AS vol_30d,
        STDDEV_POP(rate) OVER (
            ORDER BY rate_date
            ROWS BETWEEN 6  PRECEDING AND CURRENT ROW
        ) AS vol_7d,
        LN(rate / NULLIF(LAG(rate) OVER (ORDER BY rate_date), 0)) AS log_return
    FROM daily
)
SELECT
    rate_date,
    ROUND(rate,    4)                 AS rate,
    ROUND(vol_30d, 6)                 AS vol_30d,
    ROUND(vol_7d,  6)                 AS vol_7d,
    ROUND(vol_30d * SQRT(252.0), 6)  AS annualized_vol,
    CASE
        WHEN vol_30d > 1.5 THEN 'high'
        WHEN vol_30d > 0.9 THEN 'moderate'
        ELSE 'low'
    END                               AS vol_regime,
    ROUND(log_return, 6)              AS log_return
FROM with_vol
ORDER BY rate_date
"""

# real_exchange_rate: nominal rate adjusted for CPI differential.
# Base anchor uses MIN(month) — dynamic, avoids the hardcoded 2010 issue
# (CF-V7-005: BSP data starts at FX_START_YEAR >> 2010).
# References cpi_trend — returns empty until economic pipeline has run.
_REAL_EXCHANGE_RATE_SQL = """
CREATE OR REPLACE VIEW real_exchange_rate AS
WITH fx AS (
    SELECT
        date_trunc('month', rate_date)::DATE AS month,
        AVG(rate)                            AS avg_nominal_rate
    FROM stg_fx_rates
    GROUP BY 1
),
cpi AS (
    SELECT period_date AS month, cpi_index, inflation_pct
    FROM cpi_trend
    WHERE period_date IS NOT NULL
),
base AS (
    -- Dynamic anchor: first available month in the FX series.
    -- Avoids the 2010-01-01 trap when BSP data starts later (CF-V7-005).
    SELECT avg_nominal_rate AS base_nominal
    FROM fx
    ORDER BY month ASC
    LIMIT 1
),
joined AS (
    SELECT
        f.month,
        f.avg_nominal_rate  AS nominal_rate,
        c.cpi_index,
        c.inflation_pct,
        b.base_nominal
    FROM fx f
    LEFT JOIN cpi c ON f.month = c.month
    CROSS JOIN base b
    WHERE f.avg_nominal_rate IS NOT NULL
)
SELECT
    month,
    ROUND(nominal_rate, 4)                                          AS nominal_rate,
    cpi_index,
    inflation_pct,
    CASE WHEN cpi_index > 0 AND base_nominal > 0
         THEN ROUND(nominal_rate / (cpi_index / 100.0), 4)
    END                                                             AS real_rate,
    CASE WHEN cpi_index > 0 AND base_nominal > 0
         THEN ROUND(nominal_rate - (nominal_rate / (cpi_index / 100.0)), 4)
    END                                                             AS inflation_gap
FROM joined
ORDER BY month
"""

# Also fix cpi_vs_fx: old schema.sql referenced c.period + c.series_code which
# no longer exist in the new cpi_trend schema. Replace with period_date + inflation_pct.
_CPI_VS_FX_SQL = """
CREATE OR REPLACE VIEW cpi_vs_fx AS
SELECT
    c.period_date,
    c.inflation_pct                                AS cpi_yoy,
    f.rate                                         AS usdphp
FROM cpi_trend c
LEFT JOIN fx_rates f
    ON date_trunc('month', c.period_date)
     = date_trunc('month', f.rate_date)
WHERE c.inflation_pct IS NOT NULL
  AND f.currency_pair  = 'USD/PHP'
ORDER BY c.period_date
"""


# ---------------------------------------------------------------------------
# load()
# ---------------------------------------------------------------------------

def load() -> None:
    """
    Register fx_rates view and create derived FX mart views in DuckDB.
    Logs outcome to pipeline_runs.
    """
    parquet_path = PARQUET_MAP["FX_PARQUET"]

    if not parquet_path.exists():
        _log_run(status="error", rows=0,
                 error_msg=f"FX parquet not found: {parquet_path}")
        raise FileNotFoundError(
            f"FX parquet not found at {parquet_path} — run transform() first."
        )

    base_sql = (
        f"CREATE OR REPLACE VIEW fx_rates AS "
        f"SELECT * FROM read_parquet('{parquet_path.as_posix()}')"
    )

    try:
        with get_write_conn() as con:
            # Base view
            con.execute(base_sql)

            result = con.execute(
                "SELECT COUNT(*), MIN(rate_date), MAX(rate_date) FROM fx_rates "
                "WHERE currency_pair = 'USD/PHP'"
            ).fetchone()
            row_count = result[0]

            logger.info(
                "fx_rates registered: %d total rows | USD/PHP: %d [%s → %s]",
                con.execute("SELECT COUNT(*) FROM fx_rates").fetchone()[0],
                row_count,
                result[1],
                result[2],
            )

            # Derived mart views
            for label, sql in [
                ("stg_fx_rates",       _STG_FX_RATES_SQL),
                ("fx_volatility",      _FX_VOLATILITY_SQL),
                ("real_exchange_rate", _REAL_EXCHANGE_RATE_SQL),
                ("cpi_vs_fx",          _CPI_VS_FX_SQL),
            ]:
                try:
                    con.execute(sql)
                    logger.info("View created: %s", label)
                except Exception as view_exc:
                    # Non-fatal: mart views may depend on data not yet loaded.
                    # The stub from schema.sql remains. Log and continue.
                    logger.warning(
                        "View %s could not be created (non-fatal): %s",
                        label, view_exc,
                    )

            _log_run_in_conn(con, status="success", rows=row_count)

    except Exception as exc:
        _log_run(status="error", rows=0, error_msg=str(exc))
        raise


# ---------------------------------------------------------------------------
# pipeline_runs helpers — mirrors psx/load.py and bsp/load.py
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