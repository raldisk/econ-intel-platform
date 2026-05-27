"""
credit_risk pipeline — Edge C downstream consumer.

Fetches monthly BSP Circular 855 credit exposure from bsp-credit-risk-warehouse (R3).
Self-sufficient: CREDIT_RISK_API_URL absent → empty schema-compatible Parquet is written
and credit_exposure view is registered as empty. No crash, no missing view.

Pipeline grain: one row per closed YYYYMM period_key.
Schedule: 2nd of each month at 06:00 UTC (see config.CREDIT_RISK_CRON).
The 2nd-of-month ensures the prior month is closed in R3 before we request it.
"""
