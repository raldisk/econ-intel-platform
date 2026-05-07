"""
BSP extract — fetches policy rate decisions from the BSP monetary policy page.

Thin orchestrator delegating to lib/sources/bsp.fetch_policy_rates().
The shared source module handles HTTP, HTML parsing, ascending sort, and
direction computation. This module owns only the raw persistence layer.

Raw output:
  data/raw/bsp/policy_rates.json

JSON format (human-inspectable for debugging; BSP is low-volume ~5-10 decisions/year):
  [
    {
      "decision_date": "2024-06-20",
      "overnight_rp": 6.5,
      "overnight_srp": 6.5,
      "direction": "hold",
      "source": "bsp_monetary_policy"
    },
    ...
  ]

Always full refresh — no incremental logic. BSP decision history is small
enough that a full re-scrape on every scheduled run is negligible cost, and
avoids the complexity of detecting and splicing new decisions into a partial
history file.

Interface contract:
    extract() -> None
    Raises on HTTP failure or validation failure (per lib/sources/bsp._validate_policy_rates).
"""

from __future__ import annotations

import json
import logging

import config as cfg
from lib.sources.bsp import fetch_policy_rates, PolicyRate

logger = logging.getLogger(__name__)


def _raw_path():
    return cfg.BSP_RAW_DIR / "policy_rates.json"


def _serialize(records: list[PolicyRate]) -> list[dict]:
    """Serialise PolicyRate dataclass list to JSON-safe dicts."""
    return [
        {
            "decision_date": r.decision_date.isoformat(),
            "overnight_rp": r.overnight_rp,
            "overnight_srp": r.overnight_srp,
            "direction": r.direction,
            "source": r.source,
        }
        for r in records
    ]


def extract() -> None:
    """
    Fetch BSP policy rate decisions and write to data/raw/bsp/policy_rates.json.

    Raises:
      RuntimeError  — if fetch_policy_rates() returns empty (network failure
                      or page structure change)
      ValueError    — if lib/sources/bsp._validate_policy_rates() fails
                      (out-of-range rates, future dates, unknown direction)
      httpx.HTTPError — if HTTP fails after all retries
    """
    cfg.BSP_RAW_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("BSP extract: fetching policy rate decisions...")

    records = fetch_policy_rates()

    if not records:
        raise RuntimeError(
            "BSP extract: fetch_policy_rates() returned empty list — "
            "check BSP_KEY_RATE_URL accessibility and page structure. "
            f"URL: {cfg.BSP_KEY_RATE_URL}"
        )

    payload = _serialize(records)
    out_path = _raw_path()
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    logger.info(
        "BSP extract complete: %d decision records → %s", len(records), out_path
    )