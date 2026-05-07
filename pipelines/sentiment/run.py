"""
Sentiment pipeline entry point.

Scheduled: interval every 4 hours (APScheduler, cfg.SCHEDULE sentiment_interval).
Also invocable as CLI: python -m pipelines.sentiment.run

To enable live data:
  1. pip install vaderSentiment praw
  2. Set REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT
     (or TWITTER_BEARER_TOKEN for Twitter)
  3. Re-run: python -m pipelines.sentiment.run

E2E smoke:

  Row count:
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    r = con.execute(
        'SELECT COUNT(*), COUNT(DISTINCT topic), MIN(scored_at), MAX(scored_at) '
        'FROM social_sentiment'
    ).fetchone()
    print(f'rows={r[0]}, topics={r[1]}, from={r[2]}, to={r[3]}')
    con.close()
    "

  Topic sentiment summary:
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    rows = con.execute(
        'SELECT topic, ROUND(AVG(sentiment_score), 4) as avg_sent '
        'FROM social_sentiment GROUP BY 1 ORDER BY 2'
    ).fetchall()
    for r in rows: print(r)
    con.close()
    "
    → expect: food_prices most negative, psx_markets least negative

  Source check:
    python -c "
    import duckdb, config as cfg
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    rows = con.execute('SELECT source_platform, COUNT(*) FROM social_sentiment GROUP BY 1').fetchall()
    for r in rows: print(r)
    con.close()
    "
    → SYNTHETIC_FALLBACK if no credentials; REDDIT_LIVE if Reddit configured
"""

from __future__ import annotations

import logging
import sys

from pipelines.sentiment.extract   import extract
from pipelines.sentiment.transform import transform
from pipelines.sentiment.load      import load

logger = logging.getLogger(__name__)


def run() -> None:
    logger.info("=== Sentiment pipeline start ===")
    try:
        extract()
        transform()
        load()
        logger.info("=== Sentiment pipeline complete ===")
    except Exception as exc:
        logger.error("=== Sentiment pipeline FAILED: %s ===", exc)
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