"""
credit_risk/run.py
==================
Orchestration entry point for the credit_risk pipeline.

Schedule: 2nd of each month at 06:00 UTC (cfg.CREDIT_RISK_CRON).

Period key strategy:
  Always requests the PRIOR calendar month as YYYYMM.
  Rationale: R3 only serves periods with period_status='CLOSED'.
  Running on the 2nd of the month requests the prior month's closed data.
  Running on the 1st would request the current (open) month and receive a 404.
  BSP Circular 855 requires submission within 30 days of period end —
  the 2nd-of-month schedule is safely within this window.

Example:
  Runs on 2026-06-02 → requests period_key='202605' (May 2026, closed).
  Runs on 2026-05-02 → requests period_key='202504' (April 2026, closed).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from pipelines.credit_risk.extract import extract_credit_exposure
from pipelines.credit_risk.transform import transform
from pipelines.credit_risk.load import load

logger = logging.getLogger(__name__)


def _prior_month_period_key() -> str:
    """
    Return the prior calendar month as YYYYMM integer string.

    Uses UTC to avoid timezone edge cases near month boundaries.
    """
    now = datetime.now(tz=timezone.utc)
    # Subtract one month by going to first of current month, then back one day
    first_of_current = now.replace(day=1)
    last_of_prior = first_of_current.replace(
        day=1,
        month=first_of_current.month - 1 if first_of_current.month > 1 else 12,
        year=first_of_current.year if first_of_current.month > 1 else first_of_current.year - 1,
    )
    return last_of_prior.strftime("%Y%m")


def run(period_key: str | None = None) -> None:
    """
    Execute one credit_risk pipeline run.

    Args:
        period_key: Override YYYYMM period (for backfill / manual runs).
                    Defaults to prior calendar month.
    """
    resolved_key = period_key or _prior_month_period_key()
    logger.info("[credit_risk] run() starting for period_key=%s", resolved_key)

    record = extract_credit_exposure(resolved_key)
    df = transform(record)
    load(df)

    logger.info(
        "[credit_risk] run() complete for period_key=%s: %d row(s) written.",
        resolved_key, len(df),
    )


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")
    override = sys.argv[1] if len(sys.argv) > 1 else None
    run(override)
