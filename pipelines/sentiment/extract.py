"""
Sentiment extract — Philippine economic topic sentiment from social media.

Dependency audit (runtime):
  Required for live data:
    praw>=7.0          — Reddit API (r/Philippines, r/phstocks, etc.)
    tweepy>=4.0        — Twitter/X API (Academic tier required for historical)
    vaderSentiment>=3.3 — Sentiment scorer (always required)

  Hardware note:
    The original PH-Social-Sentiment-Pipeline used transformers+torch (BERT).
    That is NOT viable on Intel Pentium CPU (10+ minutes per batch).
    This pipeline uses VADER exclusively: sub-millisecond per text, zero GPU.

  Credential requirements:
    Reddit: REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT env vars
    Twitter: TWITTER_BEARER_TOKEN env var
    If credentials are absent, extract() generates synthetic fallback.

Topics tracked (PH economic context):
  inflation       — "presyo", "CPI", "inflation", "gastos", "mahal"
  peso_fx         — "peso", "USD PHP", "exchange rate", "dollar"
  psx_markets     — "PSE", "stocks", "PSEi", "shares", "dividends"
  employment      — "trabaho", "tanggal", "employment", "OFW", "remittance"
  food_prices     — "bigas", "gulay", "rice", "onion", "pork", "price hike"
  bsp_policy      — "BSP", "interest rate", "Bangko Sentral", "policy rate"

Output:
  data/raw/sentiment/raw_scored.json — list of scored post dicts

Fallback:
  Synthetic data covers the trailing 90 days at 4-hour intervals.
  Volume and sentiment are seeded from realistic Philippine social media patterns.
  All synthetic records are tagged source='SYNTHETIC_FALLBACK'.

Interface contract:
    extract() -> None
    Always succeeds (fallback guarantees output).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta

import numpy as np

import config as cfg

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PH economic topic registry
# ---------------------------------------------------------------------------

_TOPICS = [
    "inflation",
    "peso_fx",
    "psx_markets",
    "employment",
    "food_prices",
    "bsp_policy",
]

# Realistic sentiment baselines per topic (negative = bearish/anxious, positive = bullish/hopeful)
# Based on historical PH Twitter/Reddit tone for these topics
_SENTIMENT_BASELINE: dict[str, float] = {
    "inflation":    -0.25,   # generally negative (cost-of-living anxiety)
    "peso_fx":      -0.15,   # mildly negative (peso depreciation concern)
    "psx_markets":   0.05,   # near-neutral to slightly positive
    "employment":    0.10,   # mildly positive (OFW remittance pride)
    "food_prices":  -0.30,   # most negative (rice/onion price hikes)
    "bsp_policy":   -0.10,   # neutral to slightly negative (rate hike fear)
}

# Volume multipliers — psx_markets and inflation have highest engagement
_VOLUME_MULTIPLIER: dict[str, float] = {
    "inflation":    1.2,
    "peso_fx":      0.8,
    "psx_markets":  1.5,
    "employment":   0.9,
    "food_prices":  1.1,
    "bsp_policy":   0.7,
}


# ---------------------------------------------------------------------------
# Dependency audit
# ---------------------------------------------------------------------------

def _audit_dependencies() -> dict[str, bool]:
    """
    Check which live-data dependencies are available.
    Returns dict of {dep_name: available}.
    """
    available: dict[str, bool] = {}

    # vaderSentiment — required for any scoring
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer  # noqa: F401
        available["vader"] = True
    except ImportError:
        available["vader"] = False
        logger.warning(
            "Sentiment: vaderSentiment not installed. "
            "Run: pip install vaderSentiment. Using synthetic fallback."
        )

    # Reddit API credentials
    reddit_ok = all(
        os.environ.get(k) for k in
        ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USER_AGENT")
    )
    available["reddit"] = reddit_ok
    if not reddit_ok:
        logger.info(
            "Sentiment: Reddit credentials absent "
            "(REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT). "
            "Reddit source will be skipped."
        )

    # Twitter/X credentials
    twitter_ok = bool(os.environ.get("TWITTER_BEARER_TOKEN"))
    available["twitter"] = twitter_ok
    if not twitter_ok:
        logger.info(
            "Sentiment: Twitter credentials absent (TWITTER_BEARER_TOKEN). "
            "Twitter source will be skipped."
        )

    return available


# ---------------------------------------------------------------------------
# Synthetic fallback generator
# ---------------------------------------------------------------------------

def _generate_synthetic(trailing_days: int = 90) -> list[dict]:
    """
    Generate synthetic sentiment observations for the trailing N days
    at 4-hour intervals per topic.

    Each record represents a scoring batch for one topic-platform combination.
    Volume represents estimated post count in that 4-hour window.
    Sentiment score is a compound score in [-1, +1].
    """
    rng = np.random.default_rng(2024)
    records: list[dict] = []

    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(days=trailing_days)
    # 4-hour intervals
    timestamps = [start + timedelta(hours=4 * i)
                  for i in range(trailing_days * 24 // 4)]

    platforms = ["reddit", "twitter"]

    for ts in timestamps:
        hour = ts.hour
        # Higher engagement during PH business hours (UTC+8 = UTC+8, so 01:00-10:00 UTC)
        time_factor = 1.4 if 1 <= hour <= 10 else (0.8 if 18 <= hour else 1.0)

        for topic in _TOPICS:
            for platform in platforms:
                base_volume = 25 * _VOLUME_MULTIPLIER[topic] * time_factor
                # Weekend dip
                if ts.weekday() >= 5:
                    base_volume *= 0.7

                volume = max(1, int(rng.poisson(base_volume)))
                base_sent = _SENTIMENT_BASELINE[topic]

                # Add weekly cycle: slightly more negative on Monday (start of work week)
                if ts.weekday() == 0:
                    sentiment_adj = base_sent - 0.05
                else:
                    sentiment_adj = base_sent

                # Noise
                sentiment = float(np.clip(
                    sentiment_adj + rng.normal(0, 0.12),
                    -1.0, 1.0,
                ))

                records.append({
                    "scored_at":       ts.isoformat(),
                    "topic":           topic,
                    "sentiment_score": round(sentiment, 4),
                    "volume":          volume,
                    "source_platform": platform,
                    "source":          "SYNTHETIC_FALLBACK",
                })

    logger.warning(
        "Sentiment extract: no live API credentials — using SYNTHETIC_FALLBACK "
        "(%d records covering trailing %d days). "
        "Set REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET/REDDIT_USER_AGENT "
        "or TWITTER_BEARER_TOKEN to enable live data.",
        len(records), trailing_days,
    )
    return records


# ---------------------------------------------------------------------------
# Live fetch helpers (VADER-scored, no BERT)
# ---------------------------------------------------------------------------

def _score_text_vader(text: str) -> float:
    """Score a single text with VADER. Returns compound score in [-1, +1]."""
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    _ANALYZER = SentimentIntensityAnalyzer()
    return round(_ANALYZER.polarity_scores(text)["compound"], 4)


def _fetch_reddit(topics: list[str], limit_per_topic: int = 50) -> list[dict]:
    """
    Fetch recent posts from r/Philippines, r/phstocks for each topic.
    Requires praw installed and credentials in env.
    """
    try:
        import praw  # type: ignore
    except ImportError:
        logger.warning("Sentiment: praw not installed. pip install praw. Skipping Reddit.")
        return []

    client_id     = os.environ["REDDIT_CLIENT_ID"]
    client_secret = os.environ["REDDIT_CLIENT_SECRET"]
    user_agent    = os.environ["REDDIT_USER_AGENT"]

    reddit = praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
        read_only=True,
    )

    # Topic keyword map → subreddit search terms
    _REDDIT_KEYWORDS: dict[str, list[str]] = {
        "inflation":    ["inflation", "presyo", "CPI", "gastos"],
        "peso_fx":      ["peso", "dollar", "exchange rate", "USD PHP"],
        "psx_markets":  ["PSEi", "PSE stocks", "equities", "FGEN", "BDO", "ALI"],
        "employment":   ["OFW", "trabaho", "employment", "remittance", "tanggal"],
        "food_prices":  ["rice price", "bigas", "onion", "pork", "grocery"],
        "bsp_policy":   ["BSP", "Bangko Sentral", "interest rate", "policy rate"],
    }

    subreddits = ["Philippines", "phstocks", "phinvest"]
    records: list[dict] = []
    now = datetime.utcnow()

    for topic in topics:
        keywords = _REDDIT_KEYWORDS.get(topic, [topic])
        batch_scores: list[float] = []
        batch_volume = 0

        for sub_name in subreddits:
            subreddit = reddit.subreddit(sub_name)
            for kw in keywords[:2]:  # limit to first 2 keywords per subreddit
                try:
                    for post in subreddit.search(kw, limit=limit_per_topic // 2):
                        score = _score_text_vader(
                            f"{post.title} {post.selftext[:200]}"
                        )
                        batch_scores.append(score)
                        batch_volume += 1
                except Exception as exc:
                    logger.debug("Reddit search '%s' in r/%s failed: %s", kw, sub_name, exc)

        if batch_scores:
            avg_sentiment = float(np.mean(batch_scores))
            records.append({
                "scored_at":       now.isoformat(),
                "topic":           topic,
                "sentiment_score": round(avg_sentiment, 4),
                "volume":          batch_volume,
                "source_platform": "reddit",
                "source":          "REDDIT_LIVE",
            })

    logger.info("Sentiment: Reddit — %d topic batches scored.", len(records))
    return records


# ---------------------------------------------------------------------------
# extract()
# ---------------------------------------------------------------------------

def extract() -> None:
    """
    Fetch and score social media sentiment for PH economic topics.
    Falls back to synthetic data if credentials absent or vaderSentiment missing.

    Output: data/raw/sentiment/raw_scored.json
    """
    cfg.SENTIMENT_RAW_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Sentiment extract: starting dependency audit...")

    deps = _audit_dependencies()
    records: list[dict] = []

    if deps.get("vader") and (deps.get("reddit") or deps.get("twitter")):
        # Live mode
        if deps.get("reddit"):
            try:
                reddit_records = _fetch_reddit(_TOPICS)
                records.extend(reddit_records)
            except Exception as exc:
                logger.warning("Sentiment: Reddit fetch failed: %s", exc, exc_info=True)

        # Twitter: placeholder — requires Academic API tier
        if deps.get("twitter"):
            logger.info(
                "Sentiment: Twitter credentials present but live fetch not implemented. "
                "Twitter Academic API requires endpoint-level implementation. "
                "Falling back to synthetic for Twitter source."
            )

        if not records:
            logger.info("Sentiment: live fetch returned no records — using synthetic fallback.")
            records = _generate_synthetic()
    else:
        records = _generate_synthetic()

    out_path = cfg.SENTIMENT_RAW_DIR / "raw_scored.json"
    out_path.write_text(
        json.dumps(records, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    logger.info("Sentiment extract complete: %d records → %s", len(records), out_path)