-- =============================================================================
-- PH-Dashboard — DuckDB Schema Bootstrap
-- Run once at DB initialization via: python -m db.init
-- All parquet paths use the DATA_PROCESSED variable substituted at runtime.
-- Views are CREATE OR REPLACE — safe to re-run.
--
-- PLACEHOLDER PATTERN:
--   All parquet-backed views are initialised as empty-schema stubs (WHERE 1=0).
--   load.py in each pipeline replaces the stub with a live read_parquet() view
--   on first successful run.  This makes the first app launch safe regardless
--   of whether any pipeline has run.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Internal: pipeline execution log
-- ---------------------------------------------------------------------------

CREATE SEQUENCE IF NOT EXISTS pipeline_runs_seq START 1;

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id             INTEGER DEFAULT nextval('pipeline_runs_seq') PRIMARY KEY,
    pipeline       VARCHAR NOT NULL,
    status         VARCHAR NOT NULL,   -- 'success' | 'error'
    rows_affected  INTEGER DEFAULT 0,
    run_at         TIMESTAMP DEFAULT NOW(),
    error_msg      VARCHAR
);

-- ---------------------------------------------------------------------------
-- PSX — Philippine Stock Exchange prices
-- Columns: date, ticker, open, high, low, close, volume,
--          pct_change, rsi_14, ma_20, ma_50, ma_signal, volume_zscore
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW psx_prices AS
SELECT
    NULL::DATE      AS date,
    NULL::VARCHAR   AS ticker,
    NULL::DOUBLE    AS open,
    NULL::DOUBLE    AS high,
    NULL::DOUBLE    AS low,
    NULL::DOUBLE    AS close,
    NULL::BIGINT    AS volume,
    NULL::DOUBLE    AS pct_change,
    NULL::DOUBLE    AS rsi_14,
    NULL::DOUBLE    AS ma_20,
    NULL::DOUBLE    AS ma_50,
    NULL::VARCHAR   AS ma_signal,
    NULL::DOUBLE    AS volume_zscore
WHERE 1 = 0;
-- Replaced by load.py after first successful PSX pipeline run.

-- ---------------------------------------------------------------------------
-- BSP — Policy rate decisions
-- Columns: decision_date, overnight_rp, overnight_srp, direction
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW bsp_policy_rate AS
SELECT
    NULL::DATE      AS decision_date,
    NULL::DOUBLE    AS overnight_rp,
    NULL::DOUBLE    AS overnight_srp,
    NULL::VARCHAR   AS direction
WHERE 1 = 0;
-- Replaced by load.py after first successful BSP pipeline run.

-- ---------------------------------------------------------------------------
-- FX — Exchange rates (USD/PHP monthly + cross rates)
-- Columns: rate_date, currency_pair, rate, source
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW fx_rates AS
SELECT
    NULL::DATE      AS rate_date,
    NULL::VARCHAR   AS currency_pair,
    NULL::DOUBLE    AS rate,
    NULL::VARCHAR   AS source
WHERE 1 = 0;
-- Replaced by load.py after first successful FX pipeline run.

-- ---------------------------------------------------------------------------
-- Economic — GDP, CPI trend, OFW remittances
-- Ported from PH-Economic-Tracker dbt marts (two-layer: stg_ + mart)
-- ---------------------------------------------------------------------------

-- Staging views (match dbt stg_ model outputs — column renames applied here)
CREATE OR REPLACE VIEW stg_gdp AS
SELECT
    NULL::VARCHAR   AS period,
    NULL::VARCHAR   AS sector,
    NULL::DOUBLE    AS value,
    NULL::VARCHAR   AS unit
WHERE 1 = 0;

CREATE OR REPLACE VIEW stg_cpi AS
SELECT
    NULL::VARCHAR   AS period,
    NULL::VARCHAR   AS series_code,
    NULL::DOUBLE    AS value,
    NULL::VARCHAR   AS unit
WHERE 1 = 0;

CREATE OR REPLACE VIEW stg_remittances AS
SELECT
    NULL::VARCHAR   AS period,
    NULL::DOUBLE    AS amount_usd,
    NULL::VARCHAR   AS source_country
WHERE 1 = 0;

-- Mart views
CREATE OR REPLACE VIEW gdp_tracker AS
SELECT
    NULL::VARCHAR   AS period,
    NULL::VARCHAR   AS sector,
    NULL::DOUBLE    AS value,
    NULL::DOUBLE    AS qoq_change,
    NULL::DOUBLE    AS yoy_change
WHERE 1 = 0;

CREATE OR REPLACE VIEW cpi_trend AS
SELECT
    NULL::DATE      AS period_date,
    NULL::INTEGER   AS period_year,
    NULL::INTEGER   AS period_month,
    NULL::DOUBLE    AS cpi_index,
    NULL::DOUBLE    AS inflation_pct,
    NULL::DOUBLE    AS inflation_pct_wb,
    NULL::VARCHAR   AS period_label,
    NULL::DOUBLE    AS prev_cpi_index,
    NULL::DOUBLE    AS cpi_mom_change,
    NULL::DOUBLE    AS cpi_mom_pct
WHERE 1 = 0;



CREATE OR REPLACE VIEW remittance_trend AS
SELECT
    NULL::VARCHAR   AS period,
    NULL::DOUBLE    AS amount_usd,
    NULL::DOUBLE    AS mom_change,
    NULL::DOUBLE    AS yoy_change
WHERE 1 = 0;
-- All three replaced by load.py after first successful economic pipeline run.

-- ---------------------------------------------------------------------------
-- Labor — LFS labor market indicators
-- Columns: survey_round, region, employment_rate, unemployment_rate,
--          underemployment_rate
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW labor_market AS
SELECT
    NULL::VARCHAR   AS survey_round,
    NULL::VARCHAR   AS region,
    NULL::DOUBLE    AS employment_rate,
    NULL::DOUBLE    AS unemployment_rate,
    NULL::DOUBLE    AS underemployment_rate
WHERE 1 = 0;
-- Replaced by load.py after first successful labor pipeline run.

-- ---------------------------------------------------------------------------
-- Regional — FIES regional inequality
-- Columns: survey_year, region, gini_coefficient, mean_income,
--          income_share_q1..q5
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW regional_inequality AS
SELECT
    NULL::INTEGER   AS survey_year,
    NULL::VARCHAR   AS region,
    NULL::DOUBLE    AS gini_coefficient,
    NULL::DOUBLE    AS mean_income,
    NULL::DOUBLE    AS income_share_q1,
    NULL::DOUBLE    AS income_share_q2,
    NULL::DOUBLE    AS income_share_q3,
    NULL::DOUBLE    AS income_share_q4,
    NULL::DOUBLE    AS income_share_q5
WHERE 1 = 0;
-- Replaced by load.py after first successful regional pipeline run.

-- ---------------------------------------------------------------------------
-- Prices — commodity prices (DA/NFA) + food price decomposition
-- PH-Food-Price-Decomposition ONLY — PH-Price-Tracker not integrated.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW commodity_prices AS
SELECT
    NULL::DATE      AS price_date,
    NULL::VARCHAR   AS commodity_code,
    NULL::VARCHAR   AS commodity_name,
    NULL::VARCHAR   AS region,
    NULL::DOUBLE    AS price_per_kg,
    NULL::VARCHAR   AS source
WHERE 1 = 0;

CREATE OR REPLACE VIEW food_price_decomposition AS
SELECT
    NULL::DATE      AS period,
    NULL::VARCHAR   AS commodity_code,
    NULL::DOUBLE    AS observed,
    NULL::DOUBLE    AS trend,
    NULL::DOUBLE    AS seasonal,
    NULL::DOUBLE    AS residual
WHERE 1 = 0;
-- Both replaced by load.py after first successful prices pipeline run.

-- ---------------------------------------------------------------------------
-- Sentiment — social sentiment NLP pipeline
-- Columns: scored_at, topic, sentiment_score, volume, source_platform
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW social_sentiment AS
SELECT
    NULL::TIMESTAMP AS scored_at,
    NULL::VARCHAR   AS topic,
    NULL::DOUBLE    AS sentiment_score,
    NULL::INTEGER   AS volume,
    NULL::VARCHAR   AS source_platform,
    -- PATCH FINDING-012: add columns written by transform.py and referenced
    -- by _TOPIC_TREND_SQL in load.py without these columns, any dashboard query
    -- against this stub on a fresh DB raises "Binder Error: column not found"
    NULL::VARCHAR   AS sentiment_label,
    NULL::DOUBLE    AS rolling_7d_avg
WHERE 1 = 0;
-- Replaced by load.py after first successful sentiment pipeline run.

-- ---------------------------------------------------------------------------
-- COA — Commission on Audit budget utilization
-- (Phase 10 — placeholder until COA pipeline is built)
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW coa_budget_utilization AS
SELECT
    NULL::INTEGER   AS fiscal_year,
    NULL::VARCHAR   AS agency_code,
    NULL::VARCHAR   AS agency_name,
    NULL::DOUBLE    AS appropriation,
    NULL::DOUBLE    AS obligation,
    NULL::DOUBLE    AS disbursement,
    NULL::DOUBLE    AS utilization_rate,
    NULL::BOOLEAN   AS lgu_flag
WHERE 1 = 0;

-- ---------------------------------------------------------------------------
-- Cross-analysis helper views
-- These depend on the pipeline views above.  Safe to create as stubs too.
-- ---------------------------------------------------------------------------

-- PSX daily returns joined to nearest prior BSP rate decision.
-- ASOF JOIN requires bsp_policy_rate to be sorted ascending on decision_date.
-- The sorted_bsp CTE guarantees this regardless of parquet write order.
CREATE OR REPLACE VIEW psx_vs_bsp AS
WITH sorted_bsp AS (
    SELECT * FROM bsp_policy_rate ORDER BY decision_date ASC
)
SELECT
    p.date,
    p.ticker,
    p.close,
    p.pct_change,
    p.rsi_14,
    p.ma_signal,
    b.decision_date,
    b.overnight_rp    AS policy_rate,
    b.direction       AS rate_direction,
    DATEDIFF('day', b.decision_date, p.date) AS days_since_decision
FROM psx_prices p
ASOF JOIN sorted_bsp b
    ON p.date >= b.decision_date
ORDER BY p.ticker, p.date;

-- CPI YoY vs FX monthly — macro overlay
CREATE OR REPLACE VIEW cpi_vs_fx AS
SELECT
    c.period_date,
    COALESCE(c.inflation_pct, c.inflation_pct_wb) AS cpi_yoy,
    f.rate          AS usdphp
FROM cpi_trend c
LEFT JOIN fx_rates f
    ON DATE_TRUNC('month', c.period_date)
     = DATE_TRUNC('month', f.rate_date)
WHERE COALESCE(c.inflation_pct, c.inflation_pct_wb) IS NOT NULL
  AND f.currency_pair = 'USD/PHP'
ORDER BY c.period_date;


-- ---------------------------------------------------------------------------
-- FX derived views (stubs — replaced by fx/load.py)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW stg_fx_rates AS SELECT NULL::DATE AS rate_date, NULL::VARCHAR AS currency_pair, NULL::DOUBLE AS rate, NULL::VARCHAR AS source WHERE 1=0;
CREATE OR REPLACE VIEW fx_volatility AS SELECT NULL::DATE AS rate_date, NULL::DOUBLE AS rate, NULL::DOUBLE AS vol_30d, NULL::DOUBLE AS vol_7d, NULL::DOUBLE AS annualized_vol, NULL::VARCHAR AS vol_regime WHERE 1=0;
CREATE OR REPLACE VIEW real_exchange_rate AS SELECT NULL::DATE AS month, NULL::DOUBLE AS nominal_rate, NULL::DOUBLE AS cpi_index, NULL::DOUBLE AS real_rate WHERE 1=0;

-- ---------------------------------------------------------------------------
-- Economic derived views (stubs — replaced by economic/load.py)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW economic_dashboard AS SELECT NULL::INTEGER AS period_year, NULL::DOUBLE AS gdp_usd_bn, NULL::DOUBLE AS avg_inflation_pct WHERE 1=0;

-- ---------------------------------------------------------------------------
-- Prices derived views (stubs — replaced by prices/load.py)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW price_trend_by_commodity AS SELECT NULL::DATE AS month, NULL::VARCHAR AS commodity_slug, NULL::DOUBLE AS avg_price, NULL::DOUBLE AS yoy_change_pct WHERE 1=0;

-- ---------------------------------------------------------------------------
-- Sentiment derived views (stubs — replaced by sentiment/load.py)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW sentiment_topic_trend AS SELECT NULL::DATE AS obs_date, NULL::VARCHAR AS topic, NULL::DOUBLE AS avg_sentiment WHERE 1=0;

-- ---------------------------------------------------------------------------
-- COA derived views (stubs — replaced by coa/load.py)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW coa_low_utilizers AS SELECT NULL::INTEGER AS fiscal_year, NULL::VARCHAR AS agency_code, NULL::DOUBLE AS disbursement_rate WHERE 1=0;

-- ---------------------------------------------------------------------------
-- Edge A: macro lakehouse indicators (empty until economic pipeline runs with MACRO_LAKEHOUSE_URL set)
-- Grain: one row per (period, indicator_code) — long/tall format from R2 gold layer.
-- ---------------------------------------------------------------------------
CREATE VIEW IF NOT EXISTS macro_lakehouse_indicators AS
SELECT
    NULL::VARCHAR  AS period,
    NULL::VARCHAR  AS indicator_code,
    NULL::DOUBLE   AS value,
    NULL::VARCHAR  AS source
WHERE FALSE;

-- ---------------------------------------------------------------------------
-- Edge C: BSP credit exposure (empty until credit_risk pipeline runs with CREDIT_RISK_API_URL set)
-- Grain: one row per closed YYYYMM period_key (BSP Circular 855 reporting period).
-- All monetary values are USD-denominated (BSP Circular 855 reporting currency).
-- ---------------------------------------------------------------------------
CREATE VIEW IF NOT EXISTS credit_exposure AS
SELECT
    NULL::VARCHAR  AS period_key,
    NULL::DOUBLE   AS outstanding_balance_usd,
    NULL::BIGINT   AS npl_count,
    NULL::DOUBLE   AS total_rwa_usd,
    NULL::DOUBLE   AS total_provisions_usd,
    NULL::BIGINT   AS facility_count,
    NULL::VARCHAR  AS submitted_at
WHERE FALSE;
