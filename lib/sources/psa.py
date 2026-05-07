"""
Shared PSA OpenSTAT PXWeb API client.

Targets the PSA PXWeb REST API:
  Base: https://openstat.psa.gov.ph/PXWeb/api/v1/en/DB

Key series fetched:
  - CPI All Items (2018=100) — monthly
  - CPI Year-on-Year change (inflation rate) — monthly

GDP is supplemented by World Bank data via the economic pipeline; PSA GDP
via PXWeb requires complex multi-variable POST filters that vary by table
version and are not reliably stable. GDP is therefore not fetched here.

Pattern note:
  This module deliberately matches the architectural pattern of lib/sources/bsp.py:
  standalone functions, dataclass returns, httpx.Client, manual retry loop.
  tenacity and rich are not in requirements.txt and must not be used.

Usage:
    from lib.sources.psa import PSAClient, CPIRecord

    with PSAClient() as client:
        records = client.fetch_all()
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

import config as cfg

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class CPIRecord:
    """Single CPI observation returned by PSAClient."""
    series_code: str        # "CPI_ALL_ITEMS" | "CPI_YOY_CHANGE"
    period: str             # PSA PXWeb label — e.g. "2024M01"
    value: float
    unit: str               # "index (2018=100)" | "percent"
    source: str = "psa_openstat"


# ---------------------------------------------------------------------------
# PXWeb table configuration
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# MAINTENANCE NOTE — BASE YEAR REVISION
# PSA periodically updates the CPI base year (2012=100 → 2018=100 in 2020).
# The next revision will change both table paths below.
# When PSA releases a new base year, check the current paths at:
#   https://openstat.psa.gov.ph/PXWeb/pxweb/en/DB/
# and update _CPI_TABLE and _CPI_YOY_TABLE accordingly.
# The series unit string in _SERIES_MAP["CPI_ALL_ITEMS"]["unit"] should also
# be updated to reflect the new base year (e.g. "index (2025=100)").
# ---------------------------------------------------------------------------
_CPI_TABLE     = "DB__2M__PI__CPI__2018/0012M4PCPIAa.px"
_CPI_YOY_TABLE = "DB__2M__PI__CPI__2018/0022M4PCPIAb.px"

_SERIES_MAP: dict[str, dict[str, str]] = {
    "CPI_ALL_ITEMS": {
        "table": _CPI_TABLE,
        "unit": "index (2018=100)",
    },
    "CPI_YOY_CHANGE": {
        "table": _CPI_YOY_TABLE,
        "unit": "percent",
    },
}

# ---------------------------------------------------------------------------
# HTTP helpers — match bsp.py._get() pattern: manual retry + exponential backoff
# ---------------------------------------------------------------------------

_JSON_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
}


def _get_json(client: httpx.Client, url: str) -> dict[str, Any]:
    """
    GET with manual retry + exponential backoff.
    Uses cfg.HTTP_MAX_RETRIES and cfg.HTTP_BACKOFF_BASE.
    PSA_TIMEOUT (60 s) applied at client level.
    """
    last_exc: Exception = RuntimeError("no attempts made")
    for attempt in range(1, cfg.HTTP_MAX_RETRIES + 1):
        try:
            resp = client.get(url, headers=_JSON_HEADERS)
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]
        except (httpx.HTTPError, httpx.TransportError) as exc:
            last_exc = exc
            logger.warning(
                "PSA GET attempt %d/%d failed: %s", attempt, cfg.HTTP_MAX_RETRIES, exc
            )
            if attempt < cfg.HTTP_MAX_RETRIES:
                time.sleep(cfg.HTTP_BACKOFF_BASE ** attempt)
    raise last_exc


def _post_json(
    client: httpx.Client, url: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """
    POST with manual retry + exponential backoff.
    Same retry policy as _get_json.
    """
    last_exc: Exception = RuntimeError("no attempts made")
    for attempt in range(1, cfg.HTTP_MAX_RETRIES + 1):
        try:
            resp = client.post(url, json=payload, headers=_JSON_HEADERS)
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]
        except (httpx.HTTPError, httpx.TransportError) as exc:
            last_exc = exc
            logger.warning(
                "PSA POST attempt %d/%d failed: %s", attempt, cfg.HTTP_MAX_RETRIES, exc
            )
            if attempt < cfg.HTTP_MAX_RETRIES:
                time.sleep(cfg.HTTP_BACKOFF_BASE ** attempt)
    raise last_exc


# ---------------------------------------------------------------------------
# PXWeb query builder
# ---------------------------------------------------------------------------

# CF-V6-001: removed "area" (too broad — matches "CommodityArea", "UrbanArea" etc.)
# Added "geography" and "region" which are the actual PSA geographic dimension names.
_GEO_KEYWORDS = ("geo", "location", "geography", "region")


def _build_national_query(metadata: dict[str, Any]) -> dict[str, Any]:
    """
    Build a PXWeb JSON-stat query selecting Philippines-national data for
    all available time periods.

    PXWeb dimension structure:
      metadata["dataset"]["dimension"]["id"]  → list of dim names
      metadata["dataset"]["dimension"][<dim>]["category"]["index"] → code dict

    Geo dimension: select only code[0] = PHILIPPINES national total.
    All other dimensions (time, commodity): select all codes.

    Geo detection uses _GEO_KEYWORDS (lowercase substring match).
    PSA uses "GeographicArea" or "Geography" — both match via "geo" or "geography".
    """
    dataset = metadata.get("dataset") or metadata
    dimension = dataset.get("dimension", {})
    dim_ids: list[str] = dimension.get("id", [])

    variables: list[dict[str, Any]] = []
    for dim_id in dim_ids:
        dim_info = dimension.get(dim_id, {})
        index_dict: dict[str, Any] = (
            dim_info.get("category", {}).get("index", {})
        )
        all_codes = list(index_dict.keys())

        if any(tok in dim_id.lower() for tok in _GEO_KEYWORDS):
            # Geo dimension: Philippines national = first code
            selected = [all_codes[0]] if all_codes else []
        else:
            selected = all_codes

        variables.append({
            "code": dim_id,
            "selection": {"filter": "item", "values": selected},
        })

    return {"query": variables, "response": {"format": "json-stat"}}


# ---------------------------------------------------------------------------
# PXWeb response parser
# ---------------------------------------------------------------------------

def _parse_pxweb_response(
    data: dict[str, Any],
    series_code: str,
    unit: str,
) -> list[CPIRecord]:
    """
    Parse a PXWeb JSON-stat response into CPIRecord list.

    JSON-stat layout:
      dataset.value  → flat list of values
      dataset.dimension.id  → ordered list of dimension names
      dataset.dimension.<dim>.category.label  → {code: label} for that dim

    PSA dimension naming is not standardized across tables.
    We match on common patterns for the time dimension:
      "time", "year", "month", "period"
    If none match, we log with the actual dim names and return empty list.
    The diagnostic message is designed to be copy-pasteable into a bug report.
    """
    records: list[CPIRecord] = []

    try:
        dataset = data.get("dataset") or data
        dimension = data.get("dimension") or dataset.get("dimension", {})
        values: list[Any] = dataset.get("value", [])

        dim_ids: list[str] = dimension.get("id", [])

        # Locate time dimension by keyword match
        time_dim_key: Optional[str] = next(
            (
                d for d in dim_ids
                if any(t in d.lower() for t in ("time", "year", "month", "period"))
            ),
            None,
        )
        if not time_dim_key:
            logger.warning(
                "PSA: no time dimension found for series=%s. "
                "Available dimensions: %r. "
                "Expected one of: 'Time', 'Year', 'Month', 'Period'. "
                "Update _parse_pxweb_response() time_dim_key detection if PSA "
                "has changed the table's dimension naming.",
                series_code, dim_ids,
            )
            return records

        time_labels: dict[str, str] = (
            dimension.get(time_dim_key, {})
            .get("category", {})
            .get("label", {})
        )
        time_count = len(time_labels)
        if time_count == 0:
            logger.warning(
                "PSA: time dimension '%s' has no labels for series=%s.",
                time_dim_key, series_code,
            )
            return records

        # Values layout: [geo0_t0, geo0_t1, ..., geo1_t0, ...]
        # Select first geo slice (PHILIPPINES national)
        geo_count = len(values) // time_count if time_count else 1
        national_values = values[:time_count] if geo_count > 1 else values

        for idx, (_, time_label) in enumerate(time_labels.items()):
            if idx >= len(national_values):
                break
            raw_value = national_values[idx]
            if raw_value is None:
                continue
            try:
                records.append(CPIRecord(
                    series_code=series_code,
                    period=time_label,
                    value=float(raw_value),
                    unit=unit,
                ))
            except (TypeError, ValueError) as exc:
                logger.debug(
                    "PSA skip period=%s value=%r: %s", time_label, raw_value, exc
                )
                continue

    except Exception as exc:
        logger.error("PSA parse error for series=%s: %s", series_code, exc)

    return records


# ---------------------------------------------------------------------------
# PSAClient — context manager, matches PH-Economic-Tracker interface shape
# while using lib/sources/bsp.py internal conventions
# ---------------------------------------------------------------------------

class PSAClient:
    """
    Context manager client for the PSA OpenSTAT PXWeb API.

    Exposes:
      fetch_cpi()       → list[CPIRecord]  (CPI All Items, 2018=100, monthly)
      fetch_cpi_yoy()   → list[CPIRecord]  (CPI YoY inflation rate, monthly)
      fetch_all()       → list[CPIRecord]  (both series)

    Example:
        with PSAClient() as client:
            records = client.fetch_all()

    Timeout:
        PSA API is notoriously slow — cfg.PSA_TIMEOUT = 60 s is applied
        at the httpx.Client level. Retry on transport errors up to
        cfg.HTTP_MAX_RETRIES attempts with exponential backoff.
    """

    def __init__(self) -> None:
        self._client: Optional[httpx.Client] = None

    def __enter__(self) -> "PSAClient":
        self._client = httpx.Client(
            timeout=httpx.Timeout(cfg.PSA_TIMEOUT),
            follow_redirects=True,
        )
        return self

    def __exit__(self, *_: Any) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # ------------------------------------------------------------------
    # Internal fetch helper
    # ------------------------------------------------------------------

    def _fetch_series(self, series_key: str) -> list[CPIRecord]:
        if self._client is None:
            raise RuntimeError(
                "PSAClient not initialised — use as context manager: "
                "with PSAClient() as client"
            )
        meta = _SERIES_MAP[series_key]
        table_path = meta["table"]
        unit = meta["unit"]
        base_url = cfg.PSA_BASE_URL
        table_url = f"{base_url}/{table_path}"

        logger.info("PSA fetching %s ...", series_key)
        try:
            metadata = _get_json(self._client, table_url)
            query = _build_national_query(metadata)
            data = _post_json(self._client, table_url, query)
            records = _parse_pxweb_response(data, series_code=series_key, unit=unit)

            # CF-V6-002: zero-record case after successful fetch is a WARNING,
            # not INFO. It means the table path or dimension structure has changed.
            if not records:
                logger.warning(
                    "PSA %s: 0 records returned after successful fetch — "
                    "verify table path '%s' is current and the response structure "
                    "matches _parse_pxweb_response() expectations.",
                    series_key, table_path,
                )
            else:
                logger.info("PSA %s: %d records fetched.", series_key, len(records))

            return records
        except Exception as exc:
            # CF-V6-006: exc_info=True preserves the full traceback in logs.
            # This catches both HTTP failures (httpx.HTTPError re-raised by
            # _get_json/_post_json) and unexpected structure errors (KeyError,
            # AttributeError). The traceback is essential for diagnosing
            # unexpected API response shapes without re-running the fetch.
            logger.warning(
                "PSA %s failed — returning empty list: %s",
                series_key, exc,
                exc_info=True,
            )
            return []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_cpi(self) -> list[CPIRecord]:
        """Fetch CPI All Items (2018=100) monthly series from PSA OpenSTAT."""
        return self._fetch_series("CPI_ALL_ITEMS")

    def fetch_cpi_yoy(self) -> list[CPIRecord]:
        """Fetch CPI Year-on-Year inflation rate monthly series from PSA OpenSTAT."""
        return self._fetch_series("CPI_YOY_CHANGE")

    def fetch_all(self) -> list[CPIRecord]:
        """Fetch all configured PSA series (CPI All Items + CPI YoY)."""
        records: list[CPIRecord] = []
        records.extend(self.fetch_cpi())
        records.extend(self.fetch_cpi_yoy())
        return records