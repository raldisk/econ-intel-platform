"""
Sentiment load — registers social_sentiment DuckDB view and derived views.

Views:
  social_sentiment          — base view over social_sentiment.parquet
  sentiment_topic_trend     — daily average sentiment per topic
  sentiment_vs_psx          — daily sentiment overlaid with PSX close (cross-pipeline)
  sentiment_topic_heatmap   — topic × day_of_week sentiment heatmap data

Interface contract:
    load() -> None
    Raises on failure; logs to pipeline_runs.
"""

from __future__ import annotations

import logging

from db.init import PARQUET_MAP
from lib.db import get_write_conn

logger = logging.getLogger(__name__)

_PIPELINE = "sentiment"

_TOPIC_TREND_SQL = """
CREATE OR REPLACE VIEW sentiment_topic_trend AS
SELECT
    DATE_TRUNC('day', scored_at)::DATE AS obs_date,
    topic,
    ROUND(AVG(sentiment_score)::NUMERIC, 4) AS avg_sentiment,
    SUM(volume)                             AS total_volume,
    ROUND(AVG(rolling_7d_avg)::NUMERIC, 4) AS rolling_7d,
    COUNT(*)                                AS observation_count
FROM social_sentiment
GROUP BY 1, 2
ORDER BY obs_date, topic
"""

_SENTIMENT_VS_PSX_SQL = """
CREATE OR REPLACE VIEW sentiment_vs_psx AS
WITH daily_sent AS (
    SELECT
        DATE_TRUNC('day', scored_at)::DATE    AS obs_date,
        ROUND(AVG(sentiment_score)::NUMERIC, 4) AS overall_sentiment,
        SUM(volume)                              AS total_volume
    FROM social_sentiment
    GROUP BY 1
),
daily_psx AS (
    SELECT
        date AS obs_date,
        AVG(close) AS avg_close,
        SUM(volume) AS total_volume
    FROM psx_prices
    WHERE ticker = 'PSEi.PS'
    GROUP BY 1
)
SELECT
    s.obs_date,
    s.overall_sentiment,
    s.total_volume                                 AS sentiment_volume,
    p.avg_close                                    AS psei_close,
    p.total_volume                                 AS psx_volume,
    ROUND(
        CORR(s.overall_sentiment, p.avg_close)
            OVER (ORDER BY s.obs_date ROWS BETWEEN 29 PRECEDING AND CURRENT ROW)
        ::NUMERIC, 4
    ) AS rolling_30d_correlation
FROM daily_sent s
LEFT JOIN daily_psx p ON s.obs_date = p.obs_date
ORDER BY s.obs_date
"""

_HEATMAP_SQL = """
CREATE OR REPLACE VIEW sentiment_topic_heatmap AS
SELECT
    topic,
    EXTRACT(DOW FROM scored_at)::INT          AS day_of_week,
    CASE EXTRACT(DOW FROM scored_at)::INT
        WHEN 0 THEN 'Sunday'
        WHEN 1 THEN 'Monday'
        WHEN 2 THEN 'Tuesday'
        WHEN 3 THEN 'Wednesday'
        WHEN 4 THEN 'Thursday'
        WHEN 5 THEN 'Friday'
        WHEN 6 THEN 'Saturday'
    END                                       AS day_name,
    ROUND(AVG(sentiment_score)::NUMERIC, 4)  AS avg_sentiment,
    SUM(volume)                              AS total_volume
FROM social_sentiment
GROUP BY 1, 2, 3
ORDER BY topic, day_of_week
"""


def load() -> None:
    parquet_path = PARQUET_MAP["SENTIMENT_PARQUET"]

    if not parquet_path.exists():
        msg = f"Sentiment parquet not found: {parquet_path} — run transform() first."
        _log_run(status="error", rows=0, error_msg=msg)
        raise FileNotFoundError(msg)

    base_sql = (
        f"CREATE OR REPLACE VIEW social_sentiment AS "
        f"SELECT * FROM read_parquet('{parquet_path.as_posix()}')"
    )

    try:
        with get_write_conn() as con:
            con.execute(base_sql)
            row_count = con.execute("SELECT COUNT(*) FROM social_sentiment").fetchone()[0]

            logger.info(
                "social_sentiment registered: %d rows | %d topics | %s → %s",
                row_count,
                con.execute("SELECT COUNT(DISTINCT topic) FROM social_sentiment").fetchone()[0],
                con.execute("SELECT MIN(scored_at) FROM social_sentiment").fetchone()[0],
                con.execute("SELECT MAX(scored_at) FROM social_sentiment").fetchone()[0],
            )

            for label, sql in [
                ("sentiment_topic_trend",   _TOPIC_TREND_SQL),
                ("sentiment_vs_psx",        _SENTIMENT_VS_PSX_SQL),
                ("sentiment_topic_heatmap", _HEATMAP_SQL),
            ]:
                try:
                    con.execute(sql)
                    logger.info("Sentiment view created: %s", label)
                except Exception as view_exc:
                    logger.warning("Sentiment view %s failed (non-fatal): %s",
                                   label, view_exc)

            _log_run_in_conn(con, status="success", rows=row_count)

    except Exception as exc:
        _log_run(status="error", rows=0, error_msg=str(exc))
        raise


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