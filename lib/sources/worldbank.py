"""
Shared World Bank Indicators API client.

Endpoint pattern:
    GET https://api.worldbank.org/v2/country/PH/indicator/{code}
        ?format=json&per_page=100&page=N

Series fetched:
    NY.GDP.MKTP.CD        — GDP at current prices (USD) — annual
    NY.GDP.MKTP.KD.ZG     — GDP growth rate (%) — annual
    NY.GDP.PCAP.CD        — GDP per capita (current USD) — annual
    FP.CPI.TOTL.ZG        — CPI inflation (%) — annual
    SL.UEM.TOTL.ZS        — Unemployment rate (% labor force) — annual
    BX.TRF.PWKR.CD.DT     — Personal remittances received (current USD) — annual
    BX.TRF.PWKR.DT.GD.ZS  — Remittances as % of GDP — annual

Design constraints:
    - No tenacity: manual retry loop (same pattern as lib/sources/bsp.py).
    - No polars: callers use pandas.
    - No rich: stdlib logging.
    - httpx.Client (already in requirements.txt).
    - Plain Python dataclasses — no pydantic.

Usage:
    from lib.sources.worldbank import WorldBankClient, EconomicIndicator, OFWRemittance

    with WorldBankClient() as client:
        indicators = client.fetch_all_indicators()
        remittances = client.fetch_remittances()
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

import httpx

import config as cfg

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class EconomicIndicator:
    """Single annual/quarterly economic indicator observation."""
    source: str                    # 'WORLD_BANK'
    series_code: str               # 'NY.GDP.MKTP.CD' etc.
    series_name: str
    period_date: date              # Jan 1 of year for annual; first of quarter
    frequency: str                 # 'ANNUAL' | 'QUARTERLY'
    value: Optional[float]
    unit: str
    country_code: str = "PH"
    notes: Optional[str] = None


@dataclass
class OFWRemittance:
    """Annual OFW remittance record."""
    source: str                    # 'WORLD_BANK'
    period_date: date
    frequency: str                 # 'ANNUAL'
    remittance_usd: Optional[float]
    remittance_pct_gdp: Optional[float]
    country_destination: str = "ALL"
    ofw_count: Optional[int] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Indicator registry
# ---------------------------------------------------------------------------

_ECONOMIC_INDICATORS: dict[str, tuple[str, str]] = {
    "NY.GDP.MKTP.CD":    ("GDP at current prices",              "current USD"),
    "NY.GDP.MKTP.KD.ZG": ("GDP growth rate",                   "percent annual"),
    "NY.GDP.PCAP.CD":    ("GDP per capita (current USD)",       "current USD"),
    "FP.CPI.TOTL.ZG":   ("CPI inflation, consumer prices",      "percent annual"),
    "SL.UEM.TOTL.ZS":   ("Unemployment rate (% labor force)",   "percent"),
}

_REMITTANCE_CODES = (
    "BX.TRF.PWKR.CD.DT",      # USD value
    "BX.TRF.PWKR.DT.GD.ZS",  # % of GDP
)


# ---------------------------------------------------------------------------
# HTTP helpers — manual retry, same pattern as lib/sources/bsp.py
# ---------------------------------------------------------------------------

def _get_json(client: httpx.Client, url: str) -> Any:
    """
    GET with manual retry + exponential backoff.
    Uses cfg.HTTP_MAX_RETRIES and cfg.HTTP_BACKOFF_BASE.
    """
    last_exc: Exception = RuntimeError("no attempts made")
    for attempt in range(1, cfg.HTTP_MAX_RETRIES + 1):
        try:
            resp = client.get(url, headers={"Accept": "application/json"})
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, httpx.TransportError) as exc:
            last_exc = exc
            logger.warning(
                "WorldBank GET attempt %d/%d failed: %s",
                attempt, cfg.HTTP_MAX_RETRIES, exc,
            )
            if attempt < cfg.HTTP_MAX_RETRIES:
                time.sleep(cfg.HTTP_BACKOFF_BASE ** attempt)
    raise last_exc


# ---------------------------------------------------------------------------
# Pagination helper
# ---------------------------------------------------------------------------

def _fetch_all_pages(client: httpx.Client, indicator: str) -> list[dict[str, Any]]:
    """
    Fetch all paginated results for a World Bank indicator series (Philippines).

    World Bank returns: [metadata_dict, data_list]
    metadata_dict contains 'pages' key for total page count.
    """
    base = cfg.WORLD_BANK_BASE_URL
    per_page = cfg.WORLD_BANK_PER_PAGE

    url = f"{base}/country/PH/indicator/{indicator}?format=json&per_page={per_page}&page=1"
    payload = _get_json(client, url)

    if not isinstance(payload, list) or len(payload) < 2:
        logger.warning("WorldBank: unexpected response shape for %s", indicator)
        return []

    meta, first_page = payload[0], payload[1] or []
    total_pages = int(meta.get("pages", 1))
    results: list[dict[str, Any]] = list(first_page)

    for page in range(2, total_pages + 1):
        paged_url = f"{base}/country/PH/indicator/{indicator}?format=json&per_page={per_page}&page={page}"
        try:
            paged = _get_json(client, paged_url)
            if isinstance(paged, list) and len(paged) >= 2:
                results.extend(paged[1] or [])
        except Exception as exc:
            logger.warning("WorldBank page %d/%d failed for %s: %s",
                           page, total_pages, indicator, exc)

    return results


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_year_date(year_str: str) -> Optional[date]:
    """Convert '2023' → date(2023, 1, 1). Returns None if unparseable."""
    try:
        return date(int(str(year_str).strip()), 1, 1)
    except (ValueError, TypeError):
        return None


def _parse_indicators(
    raw: list[dict[str, Any]],
    series_code: str,
    series_name: str,
    unit: str,
) -> list[EconomicIndicator]:
    records: list[EconomicIndicator] = []
    for point in raw:
        if point.get("value") is None:
            continue
        year_str = point.get("date", "")
        period = _parse_year_date(year_str)
        if period is None:
            continue
        if period.year < cfg.ECONOMIC_START_YEAR:
            continue
        try:
            records.append(EconomicIndicator(
                source="WORLD_BANK",
                series_code=series_code,
                series_name=series_name,
                period_date=period,
                frequency="ANNUAL",
                value=float(point["value"]),
                unit=unit,
                country_code="PH",
            ))
        except (TypeError, ValueError) as exc:
            logger.debug("WorldBank skip %s %s: %s", series_code, year_str, exc)
    return records


def _parse_remittances(
    raw_usd: list[dict[str, Any]],
    raw_pct: list[dict[str, Any]],
) -> list[OFWRemittance]:
    usd_by_year = {
        p["date"]: float(p["value"])
        for p in raw_usd
        if p.get("value") is not None
    }
    pct_by_year = {
        p["date"]: float(p["value"])
        for p in raw_pct
        if p.get("value") is not None
    }
    all_years = sorted(set(usd_by_year) | set(pct_by_year))
    records: list[OFWRemittance] = []
    for year_str in all_years:
        period = _parse_year_date(year_str)
        if period is None or period.year < cfg.ECONOMIC_START_YEAR:
            continue
        usd_val = usd_by_year.get(year_str)
        pct_val = pct_by_year.get(year_str)
        if usd_val is None and pct_val is None:
            continue
        records.append(OFWRemittance(
            source="WORLD_BANK",
            period_date=period,
            frequency="ANNUAL",
            remittance_usd=usd_val,
            remittance_pct_gdp=pct_val,
            country_destination="ALL",
            notes="World Bank WDI — personal remittances received",
        ))
    return records


# ---------------------------------------------------------------------------
# WorldBankClient
# ---------------------------------------------------------------------------

class WorldBankClient:
    """
    Context manager client for the World Bank Indicators API.

    Fetches GDP, CPI (annual), employment, and OFW remittance series for PH.
    No authentication required. Pagination handled automatically.

    Usage:
        with WorldBankClient() as client:
            indicators = client.fetch_all_indicators()
            remittances = client.fetch_remittances()
    """

    def __init__(self) -> None:
        self._client: Optional[httpx.Client] = None

    def __enter__(self) -> "WorldBankClient":
        self._client = httpx.Client(
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
        )
        return self

    def __exit__(self, *_: Any) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def fetch_indicator(self, code: str) -> list[EconomicIndicator]:
        if self._client is None:
            raise RuntimeError(
                "WorldBankClient not initialised — use as context manager"
            )
        if code not in _ECONOMIC_INDICATORS:
            raise ValueError(f"Unknown indicator code: {code!r}")
        series_name, unit = _ECONOMIC_INDICATORS[code]
        logger.info("WorldBank fetching %s ...", code)
        try:
            raw = _fetch_all_pages(self._client, code)
            records = _parse_indicators(raw, code, series_name, unit)
            logger.info("WorldBank %s: %d records.", code, len(records))
            return records
        except Exception as exc:
            logger.warning("WorldBank %s failed — returning empty: %s", code, exc,
                           exc_info=True)
            return []

    def fetch_all_indicators(self) -> list[EconomicIndicator]:
        """Fetch all configured economic indicator series."""
        all_records: list[EconomicIndicator] = []
        for code in _ECONOMIC_INDICATORS:
            all_records.extend(self.fetch_indicator(code))
        return all_records

    def fetch_remittances(self) -> list[OFWRemittance]:
        """Fetch OFW remittance series (USD + % of GDP) and merge."""
        if self._client is None:
            raise RuntimeError(
                "WorldBankClient not initialised — use as context manager"
            )
        logger.info("WorldBank fetching OFW remittances ...")
        try:
            raw_usd = _fetch_all_pages(self._client, _REMITTANCE_CODES[0])
            raw_pct = _fetch_all_pages(self._client, _REMITTANCE_CODES[1])
            records = _parse_remittances(raw_usd, raw_pct)
            logger.info("WorldBank remittances: %d records.", len(records))
            return records
        except Exception as exc:
            logger.warning("WorldBank remittances failed — returning empty: %s", exc,
                           exc_info=True)
            return []