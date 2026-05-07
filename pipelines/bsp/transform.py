"""
BSP transform — converts raw policy_rates.json to a clean parquet.

Input:  data/raw/bsp/policy_rates.json
Output: data/processed/bsp/bsp_policy_rate.parquet

Schema:
    decision_date   TIMESTAMP   — date of BSP Monetary Board decision
    overnight_rp    DOUBLE      — Overnight Reverse Repurchase (borrowing) rate
    overnight_srp   DOUBLE      — Special Deposit Account rate (nullable)
    direction       VARCHAR     — "hike" | "cut" | "hold"
    source          VARCHAR     — "bsp_monetary_policy"

SORT ORDER:
    Sorted ascending by decision_date — required by the ASOF JOIN in schema.sql
    that produces psx_vs_bsp. L006: always sort the right-side table ascending
    on the join key before writing parquet. Never assume write order is correct.
"""

from __future__ import annotations

import json
import logging
from datetime import date

import pandas as pd

import config as cfg
from db.init import PARQUET_MAP

logger = logging.getLogger(__name__)

_VALID_DIRECTIONS = frozenset({"hike", "cut", "hold"})


def transform() -> None:
    """
    Read raw JSON, validate, produce clean bsp_policy_rate.parquet.
    Sorted ascending by decision_date (ASOF JOIN requirement — L006).
    Raises on missing input or schema violations.
    """
    raw_path = cfg.BSP_RAW_DIR / "policy_rates.json"
    if not raw_path.exists():
        raise FileNotFoundError(
            f"BSP raw file not found: {raw_path} — run extract() first."
        )

    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    if not raw:
        raise ValueError("BSP raw JSON is empty — extract produced no records.")

    records = []
    for item in raw:
        d = date.fromisoformat(item["decision_date"])
        rrp = float(item["overnight_rp"])
        srp = float(item["overnight_srp"]) if item["overnight_srp"] is not None else None
        direction = item["direction"]

        if direction not in _VALID_DIRECTIONS:
            raise ValueError(
                f"Invalid direction '{direction}' at {d} — "
                f"expected one of {sorted(_VALID_DIRECTIONS)}"
            )

        records.append({
            "decision_date": d,
            "overnight_rp": rrp,
            "overnight_srp": srp,
            "direction": direction,
            "source": item.get("source", "bsp_monetary_policy"),
        })

    df = pd.DataFrame(records)
    df["decision_date"] = pd.to_datetime(df["decision_date"])

    # Explicit ascending sort required by ASOF JOIN (L006).
    # BSP HTML tables are commonly descending — raw JSON preserves parse order.
    # Sorting here guarantees parquet write order regardless of source layout.
    df.sort_values("decision_date", ascending=True, inplace=True)
    df.reset_index(drop=True, inplace=True)

    # Schema coercion
    df["overnight_rp"] = df["overnight_rp"].astype(float)
    # overnight_srp is nullable — use pandas nullable Float64
    df["overnight_srp"] = df["overnight_srp"].astype("Float64")
    df["direction"] = df["direction"].astype(str)
    df["source"] = df["source"].astype(str)

    out_path = PARQUET_MAP["BSP_PARQUET"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)

    logger.info(
        "BSP transform complete: %d records | %s → %s | latest decision: %s (%s) → %s",
        len(df),
        df["decision_date"].min().date(),
        df["decision_date"].max().date(),
        df["decision_date"].max().date(),
        df.loc[df["decision_date"].idxmax(), "direction"],
        out_path,
    )