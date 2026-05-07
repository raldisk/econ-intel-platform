"""
Shared BSP (Bangko Sentral ng Pilipinas) data client.

Covers two distinct BSP data surfaces:

  1. FX rates — Table 12 (USD/PHP monthly) and Table 13 (cross rates).
     Adapted from PH-FX-Dashboard / src/ph_fx/ingestion/bsp_historical.py.

  2. Policy rate — overnight borrowing/lending rates from the BSP
     monetary policy page. Scraped from the published rate table.

Both are exposed as standalone functions — no class required.
Import what you need:

    from lib.sources.bsp import fetch_monthly_usdphp, fetch_policy_rates
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date
from typing import Optional

import httpx
from bs4 import BeautifulSoup

import config as cfg

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes — intentionally plain, no ORM dependency
# ---------------------------------------------------------------------------

@dataclass
class FXRate:
    rate_date: date
    currency_pair: str
    rate: float
    source: str


@dataclass
class CrossRate:
    rate_date: date
    base_currency: str
    php_rate: float
    source: str


@dataclass
class PolicyRate:
    decision_date: date
    overnight_rp: float        # Reverse Repurchase (borrowing) rate
    overnight_srp: Optional[float]  # Special Deposit Account rate
    direction: str             # "hike" | "cut" | "hold"
    source: str = "bsp_monetary_policy"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

CROSS_CURRENCIES = ["EUR", "JPY", "GBP", "SGD", "AUD", "HKD", "CAD", "CNY"]

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Plausible range for BSP overnight RRP — sanity guard, not a policy view.
_RATE_MIN = 0.5
_RATE_MAX = 20.0


def _get(url: str) -> str:
    """
    HTTP GET with retry + exponential backoff.
    Returns response text or raises on exhausted retries.
    """
    last_exc: Exception = RuntimeError("no attempts made")
    for attempt in range(1, cfg.HTTP_MAX_RETRIES + 1):
        try:
            resp = httpx.get(
                url,
                headers=cfg.HTTP_HEADERS,
                timeout=cfg.HTTP_TIMEOUT,
                follow_redirects=True,
            )
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as exc:
            last_exc = exc
            logger.warning("BSP GET attempt %d/%d failed: %s", attempt, cfg.HTTP_MAX_RETRIES, exc)
            if attempt < cfg.HTTP_MAX_RETRIES:
                time.sleep(cfg.HTTP_BACKOFF_BASE ** attempt)
    raise last_exc


# ---------------------------------------------------------------------------
# FX — Table 12 (USD/PHP monthly)
# ---------------------------------------------------------------------------

def fetch_monthly_usdphp(start_year: int = cfg.BSP_START_YEAR) -> list[FXRate]:
    """
    Scrape BSP Table 12 — monthly average USD/PHP from start_year to present.
    Returns list of FXRate records.
    """
    html = _get(cfg.BSP_TABLE12_URL)
    records: list[FXRate] = []
    soup = BeautifulSoup(html, "html.parser")
    for row in soup.select("table tr"):
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if not cells:
            continue
        try:
            year = int(cells[0])
        except ValueError:
            continue
        if year < start_year:
            continue
        for i, month_name in enumerate(MONTHS):
            if i + 1 >= len(cells):
                break
            raw = cells[i + 1].replace(",", "").strip()
            if not raw or raw in ("-", ".."):
                continue
            try:
                records.append(FXRate(
                    rate_date=date(year, i + 1, 1),
                    currency_pair="USD/PHP",
                    rate=float(raw),
                    source="bsp_table12",
                ))
            except ValueError:
                continue
    logger.info("BSP Table 12: %d monthly records fetched.", len(records))
    return records


# ---------------------------------------------------------------------------
# FX — Table 13 (cross rates)
# ---------------------------------------------------------------------------

def fetch_cross_rates() -> list[CrossRate]:
    """
    Scrape BSP Table 13 — latest cross rates vs PHP.
    Returns list of CrossRate records.
    """
    html = _get(cfg.BSP_TABLE13_URL)
    records: list[CrossRate] = []
    soup = BeautifulSoup(html, "html.parser")
    ref_date = date.today()
    for row in soup.select("table tr"):
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cells) < 2:
            continue
        currency = cells[0].upper().strip()
        if currency not in CROSS_CURRENCIES:
            continue
        raw = cells[1].replace(",", "").strip()
        try:
            records.append(CrossRate(
                rate_date=ref_date,
                base_currency=currency,
                php_rate=float(raw),
                source="bsp_table13",
            ))
        except ValueError:
            continue
    logger.info("BSP Table 13: %d cross rate records fetched.", len(records))
    return records


# ---------------------------------------------------------------------------
# Policy rate
# ---------------------------------------------------------------------------

def fetch_policy_rates() -> list[PolicyRate]:
    """
    Scrape BSP monetary policy key rates page.
    Returns list of PolicyRate records sorted ascending by decision_date.

    BSP publishes a table of historical overnight RRP rates. Direction is
    computed by comparing each rate to the previous row after ascending sort —
    never inferred from HTML table order, which may be descending.

    Raises ValueError if parsed rates fail sanity checks (out-of-range values,
    future dates, unknown direction strings). A corrupted rate table is a hard
    failure — silently wrong BSP data in psx_vs_bsp is worse than no data.
    """
    html = _get(cfg.BSP_KEY_RATE_URL)
    soup = BeautifulSoup(html, "html.parser")
    records: list[PolicyRate] = []

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row in rows:
            cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            decision_date = _parse_bsp_date(cells[0])
            if decision_date is None:
                continue
            rrp = _parse_rate(cells[1])
            if rrp is None:
                continue
            srp = _parse_rate(cells[2]) if len(cells) > 2 else None
            records.append(PolicyRate(
                decision_date=decision_date,
                overnight_rp=rrp,
                overnight_srp=srp,
                direction="hold",   # computed below after explicit ascending sort
            ))

    if not records:
        logger.warning("BSP policy rates: no records parsed — check page structure.")
        return records

    # ---------------------------------------------------------------------------
    # Explicit ascending sort before direction computation.
    # BSP HTML tables are commonly descending (latest first).  Sorting here
    # guarantees direction is computed chronologically regardless of HTML order.
    # ---------------------------------------------------------------------------
    records.sort(key=lambda r: r.decision_date)

    for i, rec in enumerate(records):
        if i == 0:
            rec.direction = "hold"
        else:
            prev = records[i - 1].overnight_rp
            if rec.overnight_rp > prev:
                rec.direction = "hike"
            elif rec.overnight_rp < prev:
                rec.direction = "cut"
            else:
                rec.direction = "hold"

    # ---------------------------------------------------------------------------
    # Post-parse validation — raise on any record that fails sanity checks.
    # A bad rate corrupts psx_vs_bsp (the primary interview demo surface).
    # ---------------------------------------------------------------------------
    _validate_policy_rates(records)

    logger.info("BSP policy rates: %d decision records fetched.", len(records))
    return records


def _validate_policy_rates(records: list[PolicyRate]) -> None:
    """
    Raise ValueError if any parsed PolicyRate fails sanity checks.
    Called after sort + direction computation — before returning to caller.
    """
    today = date.today()
    for r in records:
        if not (_RATE_MIN <= r.overnight_rp <= _RATE_MAX):
            raise ValueError(
                f"BSP rate out of plausible range [{_RATE_MIN}, {_RATE_MAX}]: "
                f"date={r.decision_date}, overnight_rp={r.overnight_rp}"
            )
        if r.direction not in ("hike", "cut", "hold"):
            raise ValueError(
                f"Unknown BSP direction value: '{r.direction}' "
                f"at date={r.decision_date}"
            )
        if r.decision_date > today:
            raise ValueError(
                f"BSP decision date is in the future: {r.decision_date} "
                f"(today={today}) — check page structure"
            )


# ---------------------------------------------------------------------------
# Parse helpers
# ---------------------------------------------------------------------------

_BSP_DATE_FMTS = ["%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d", "%d-%b-%Y"]


def _parse_bsp_date(raw: str) -> Optional[date]:
    """Try multiple date formats against a raw BSP cell string."""
    from datetime import datetime
    raw = raw.strip()
    for fmt in _BSP_DATE_FMTS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_rate(raw: str) -> Optional[float]:
    """Parse a rate cell — strips %, commas, whitespace."""
    cleaned = raw.strip().replace("%", "").replace(",", "").strip()
    if not cleaned or cleaned in ("-", ".."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None