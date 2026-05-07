"""
Sentiment transform — aggregates raw scored posts to social_sentiment parquet.

Input:
  data/raw/sentiment/raw_scored.json

Output:
  data/processed/sentiment/social_sentiment.parquet
    Columns:
      scored_at        datetime64   — observation timestamp (hourly bucket)
      topic            str          — one of 6 PH economic topics
      sentiment_score  float64      — compound VADER score in [-1, +1]
      volume           int64        — number of posts in the bucket
      source_platform  str          — "reddit" | "twitter" | "SYNTHETIC_FALLBACK"
      sentiment_label  str          — "positive" | "negative" | "neutral"
      rolling_7d_avg   float64      — 7-day rolling average sentiment per topic

Derived columns:
  sentiment_label:   positive (>0.05), negative (<-0.05), neutral
  rolling_7d_avg:    rolling 7-day mean per topic, sorted chronologically
  topic_rank:        volume rank across topics per day (for heatmap viz)
"""

from __future__ import annotations

import json
import logging

import pandas as pd

import config as cfg
from db.init import PARQUET_MAP

logger = logging.getLogger(__name__)


def transform() -> None:
    raw_path = cfg.SENTIMENT_RAW_DIR / "raw_scored.json"
    if not raw_path.exists():
        raise FileNotFoundError(
            f"Sentiment raw file not found: {raw_path} — run extract() first."
        )

    records = json.loads(raw_path.read_text(encoding="utf-8"))
    if not records:
        raise ValueError("Sentiment transform: raw_scored.json is empty.")

    df = pd.DataFrame(records)

    # Type coercion
    df["scored_at"]       = pd.to_datetime(df["scored_at"], errors="coerce", utc=True)
    df["sentiment_score"] = pd.to_numeric(df["sentiment_score"], errors="coerce")
    df["volume"]          = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")
    df = df.dropna(subset=["scored_at", "sentiment_score"])

    if df.empty:
        raise ValueError("Sentiment transform: no valid records after cleaning.")

    # Clamp sentiment to [-1, +1]
    df["sentiment_score"] = df["sentiment_score"].clip(-1.0, 1.0).round(4)

    # Sentiment label
    df["sentiment_label"] = "neutral"
    df.loc[df["sentiment_score"] >  0.05, "sentiment_label"] = "positive"
    df.loc[df["sentiment_score"] < -0.05, "sentiment_label"] = "negative"

    # Ensure source_platform
    if "source_platform" not in df.columns:
        df["source_platform"] = "unknown"
    df["source_platform"] = df["source_platform"].astype(str)

    # Sort for rolling calculation
    df = df.sort_values(["topic", "scored_at"]).reset_index(drop=True)

    # 7-day rolling average per topic
    # Convert to float to avoid pandas groupby rolling issues
    df["_sent_float"] = df["sentiment_score"].astype(float)
    rolling = (
        df.set_index("scored_at")
        .groupby("topic")["_sent_float"]
        .transform(lambda s: s.rolling("7D", min_periods=1).mean())
    )
    df["rolling_7d_avg"] = rolling.round(4).values
    df = df.drop(columns=["_sent_float"])

    # Final column order
    cols = [
        "scored_at", "topic", "sentiment_score", "volume",
        "source_platform", "sentiment_label", "rolling_7d_avg",
    ]
    df = df[cols]

    out_path = PARQUET_MAP["SENTIMENT_PARQUET"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)

    logger.info(
        "Sentiment transform complete: %d rows | %d topics | %s → %s | "
        "label dist: %s → %s",
        len(df),
        df["topic"].nunique(),
        df["scored_at"].min(),
        df["scored_at"].max(),
        df["sentiment_label"].value_counts().to_dict(),
        out_path,
    )