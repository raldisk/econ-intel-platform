"""
credit_risk/extract.py
======================
Pull monthly credit exposure from bsp-credit-risk-warehouse (R3) FastAPI.

API contract (R3 GET /credit-exposure?period_key=YYYYMM):
  Response columns (verified against R3 CreditExposureResponse Pydantic model
  and V002__fact_credit_exposure.sql DDL):
    period_key                      (INTEGER as string in JSON)
    total_outstanding_balance_usd   — SUM of outstanding_balance_usd across facilities
    npl_count                       — COUNT of facilities with npl_flag=TRUE
    total_risk_weighted_asset_usd   — SUM of risk_weighted_asset_usd
    total_provision_amount_usd      — SUM of provision_amount_usd
    facility_count                  — COUNT(*) total facilities
    submitted_at                    — MAX(insertion_timestamp) as text

Fallback: CREDIT_RISK_API_URL absent or R3 unreachable → return None.
Caller (run.py) writes empty-schema Parquet on None return.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import httpx

import config as cfg

logger = logging.getLogger(__name__)


@dataclass
class CreditExposureRecord:
    """
    One closed BSP Circular 855 reporting period.
    All monetary values in USD at prevailing BSP reference rate.
    Verified against R3 V002__fact_credit_exposure.sql DDL.
    """
    period_key: str               # YYYYMM integer serialised as string
    outstanding_balance_usd: float
    npl_count: int                # facilities with npl_flag=TRUE
    total_rwa_usd: float          # SUM(risk_weighted_asset_usd)
    total_provisions_usd: float   # SUM(provision_amount_usd)
    facility_count: int
    submitted_at: Optional[str]   # ISO timestamp string or None


def extract_credit_exposure(period_key: str) -> Optional[CreditExposureRecord]:
    """
    Fetch credit exposure for a given closed period from R3.

    Args:
        period_key: YYYYMM string, e.g. '202504'.

    Returns:
        CreditExposureRecord on success.
        None if CREDIT_RISK_API_URL is absent, R3 is unreachable, or
        the period is not found / not yet closed in R3.
    """
    if not cfg.CREDIT_RISK_API_URL:
        logger.debug("[credit_risk] CREDIT_RISK_API_URL not set — enrichment disabled.")
        return None

    url = f"{cfg.CREDIT_RISK_API_URL.rstrip('/')}/credit-exposure"
    try:
        resp = httpx.get(
            url,
            params={"period_key": period_key},
            timeout=cfg.CREDIT_RISK_TIMEOUT,
        )
        if resp.status_code == 404:
            logger.warning(
                "[credit_risk] R3 returned 404 for period_key=%s. "
                "Period may not be closed yet or data absent.",
                period_key,
            )
            return None
        resp.raise_for_status()
        d = resp.json()

        return CreditExposureRecord(
            period_key=str(d["period_key"]),
            outstanding_balance_usd=float(d["total_outstanding_balance_usd"]),
            npl_count=int(d.get("npl_count", 0)),
            total_rwa_usd=float(d["total_risk_weighted_asset_usd"]),
            total_provisions_usd=float(d["total_provision_amount_usd"]),
            facility_count=int(d["facility_count"]),
            submitted_at=d.get("submitted_at"),
        )

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[credit_risk] R3 unavailable for period_key=%s (%s: %s) — "
            "writing empty credit_exposure view.",
            period_key, type(exc).__name__, exc,
        )
        return None
