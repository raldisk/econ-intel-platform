"""
Economic extract — fetches PSA CPI, World Bank macro series, and optional BSP remittances.

Sources:
  psa          — CPI All Items + CPI YoY (monthly) via lib/sources/psa.PSAClient
  worldbank    — GDP, CPI annual, unemployment, OFW remittances via lib/sources/worldbank
  bsp_csv      — Optional BSP monthly remittance CSV (path from cfg.BSP_REMITTANCE_CSV)

Raw output:
  data/raw/economic/indicators.json   — EconomicIndicator records as dicts
  data/raw/economic/remittances.json  — OFWRemittance records as dicts

PSA → EconomicIndicator conversion (CF-V7-006):
  lib/sources/psa.CPIRecord has period: str (e.g. "2024M01").
  _parse_period_str() converts that to a YYYY-MM-DD ISO date string.
  EconomicIndicator.period_date is stored as ISO string for JSON serialisation.

Dependencies:
  httpx (requirements.txt), lib/sources/psa, lib/sources/worldbank
  beautifulsoup4 is NOT needed here — BSP CSV is plain-text parsing.

Interface contract:
    extract() -> None
    Raises RuntimeError only if ALL sources fail with zero records.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import date
from pathlib import Path
from typing import Optional

import config as cfg
import httpx as _httpx  # prefixed to avoid namespace collision
from lib.sources.psa import PSAClient
from lib.sources.worldbank import WorldBankClient, EconomicIndicator, OFWRemittance

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Period string → ISO date conversion (CF-V7-006)
# PSA PXWeb returns period labels like "2024M01", "2023M12", etc.
# ---------------------------------------------------------------------------

def _parse_period_str(period: str) -> Optional[str]:
    """
    Convert PSA period string to ISO date string (YYYY-MM-DD).

    Handles:
        "2024M01"  → "2024-01-01"
        "2024-01"  → "2024-01-01"
        "2024"     → "2024-01-01"
        "2024Q1"   → "2024-01-01"

    Returns None if the format is unrecognised.
    """
    p = period.strip()
    try:
        if "M" in p.upper():
            # "2024M01"
            parts = p.upper().split("M")
            return date(int(parts[0]), int(parts[1]), 1).isoformat()
        if "Q" in p.upper():
            # "2024Q1"
            parts = p.upper().split("Q")
            month = (int(parts[1]) - 1) * 3 + 1
            return date(int(parts[0]), month, 1).isoformat()
        if "-" in p and len(p) == 7:
            # "2024-01"
            year_s, mon_s = p.split("-")
            return date(int(year_s), int(mon_s), 1).isoformat()
        if len(p) == 4 and p.isdigit():
            # "2024"
            return date(int(p), 1, 1).isoformat()
    except (ValueError, IndexError):
        pass
    logger.debug("_parse_period_str: unrecognised format %r — skipping.", period)
    return None


# ---------------------------------------------------------------------------
# CPIRecord → EconomicIndicator dict conversion
# ---------------------------------------------------------------------------

def _cpi_records_to_dicts(records) -> list[dict]:
    """Convert CPIRecord list from lib/sources/psa to EconomicIndicator dicts."""
    result = []
    for r in records:
        period_iso = _parse_period_str(r.period)
        if period_iso is None:
            continue
        result.append({
            "source": "PSA",
            "series_code": r.series_code,
            "series_name": (
                "Consumer Price Index - All Items (2018=100)"
                if r.series_code == "CPI_ALL_ITEMS"
                else "CPI Year-on-Year Change - All Items"
            ),
            "period_date": period_iso,
            "frequency": "MONTHLY",
            "value": r.value,
            "unit": r.unit,
            "country_code": "PH",
            "notes": None,
        })
    return result


# ---------------------------------------------------------------------------
# Optional BSP remittance CSV parser
# ---------------------------------------------------------------------------

_MONTH_MAP = {
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
    "jan":1,"feb":2,"mar":3,"apr":4,"jun":6,"jul":7,
    "aug":8,"sep":9,"oct":10,"nov":11,"dec":12,
}


def _parse_bsp_csv(csv_path: Path) -> list[dict]:
    """
    Parse BSP monthly remittance CSV into OFWRemittance-compatible dicts.
    Expected columns: Year, Month, Total (USD Millions), ...

    Returns empty list if path is None, doesn't exist, or parsing fails.
    Always called defensively — BSP CSV is optional enrichment, never required.
    """
    if not csv_path or not csv_path.exists():
        logger.info("BSP remittance CSV not configured or not found — skipping.")
        return []

    records = []
    try:
        content = csv_path.read_text(encoding="utf-8-sig")
        rows = list(csv.reader(io.StringIO(content)))
        # Find first data row (first column parseable as a year integer)
        data_start = 0
        for i, row in enumerate(rows):
            if row and str(row[0]).strip().isdigit():
                data_start = i
                break

        for row in rows[data_start:]:
            if len(row) < 3:
                continue
            try:
                year = int(str(row[0]).strip())
                month_str = str(row[1]).strip().lower()
                month = _MONTH_MAP.get(month_str) if not month_str.isdigit() else int(month_str)
                if not month or year < cfg.ECONOMIC_START_YEAR:
                    continue
                raw_val = str(row[2]).strip().replace(",", "").replace(" ", "")
                if not raw_val or raw_val in ("-", "..", "N/A", "n/a"):
                    continue
                # BSP reports in USD millions
                usd_val = float(raw_val) * 1_000_000
                records.append({
                    "source": "BSP",
                    "period_date": date(year, month, 1).isoformat(),
                    "frequency": "MONTHLY",
                    "remittance_usd": usd_val,
                    "remittance_pct_gdp": None,
                    "country_destination": "ALL",
                    "ofw_count": None,
                    "notes": "BSP monthly remittances (land-based + sea-based)",
                })
            except (ValueError, TypeError) as exc:
                logger.debug("BSP CSV skip row %r: %s", row, exc)
    except Exception as exc:
        logger.warning("BSP CSV parse error: %s", exc, exc_info=True)

    logger.info("BSP CSV: %d monthly remittance records.", len(records))
    return records


# ---------------------------------------------------------------------------
# Edge A: R2 lakehouse gold-layer adapter — macro indicators
#
# Data contract (R2 pipeline/contracts/gold_macro_indicators.yaml):
#   Columns: period (date), indicator_code (string), value (double), source (string)
#   Format: long/tall — one row per (period, indicator_code) combination
#   Example indicator_codes: "CPI", "GDP_GROWTH", "UNEMPLOYMENT", etc.
#
# Design decision (additive enrichment, not replacement):
#   Rather than attempting to map this long-format data to the existing
#   EconomicIndicator dataclass (which has a fixed wide schema from worldbank.py),
#   the lakehouse adapter writes a SEPARATE raw file (lakehouse_macro.parquet)
#   that is loaded as its own DuckDB view: macro_lakehouse_indicators.
#
# DDIA: any failure → None returned → existing pipeline runs normally.
# ---------------------------------------------------------------------------

@dataclass
class LakehouseMacroRecord:
    """Raw record from R2 gold_macro_indicators endpoint."""
    period: str           # ISO date string (YYYY-MM-DD)
    indicator_code: str   # e.g. "CPI", "GDP_GROWTH"
    value: float
    source: str           # original R2 source tag


def _try_lakehouse_macro() -> list[LakehouseMacroRecord] | None:
    """
    Attempt to pull macro indicators from R2 gold layer.

    Returns list[LakehouseMacroRecord] on success, None on any failure.
    """
    if not cfg.MACRO_LAKEHOUSE_URL:
        return None

    url = f"{cfg.MACRO_LAKEHOUSE_URL.rstrip('/')}/gold/gold_macro_indicators/data"
    try:
        resp = _httpx.get(url, timeout=cfg.MACRO_LAKEHOUSE_TIMEOUT)
        resp.raise_for_status()
        rows: list[dict] = resp.json()

        if not rows:
            logger.warning("[economic] Lakehouse returned 0 macro rows.")
            return None

        records = []
        skipped = 0
        for r in rows:
            try:
                records.append(
                    LakehouseMacroRecord(
                        period=str(r["period"]),
                        indicator_code=str(r["indicator_code"]),
                        value=float(r["value"]),
                        source=str(r.get("source", "macro_lakehouse")),
                    )
                )
            except (KeyError, TypeError, ValueError) as row_exc:
                skipped += 1
                logger.debug("[economic] Skipped malformed macro row: %s — %s", r, row_exc)

        if skipped:
            logger.warning("[economic] Skipped %d malformed macro rows.", skipped)

        if not records:
            return None

        logger.info("[economic] Lakehouse enrichment: %d macro records from R2.", len(records))
        return records

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[economic] Lakehouse macro unavailable (%s: %s) — "
            "embedded PSA/World Bank pipeline continues normally.",
            type(exc).__name__, exc,
        )
        return None


# ---------------------------------------------------------------------------
# EconomicIndicator / OFWRemittance → dict converters for World Bank records
# ---------------------------------------------------------------------------

def _indicator_to_dict(r: EconomicIndicator) -> dict:
    return {
        "source": r.source,
        "series_code": r.series_code,
        "series_name": r.series_name,
        "period_date": r.period_date.isoformat(),
        "frequency": r.frequency,
        "value": r.value,
        "unit": r.unit,
        "country_code": r.country_code,
        "notes": r.notes,
    }


def _remittance_to_dict(r: OFWRemittance) -> dict:
    return {
        "source": r.source,
        "period_date": r.period_date.isoformat(),
        "frequency": r.frequency,
        "remittance_usd": r.remittance_usd,
        "remittance_pct_gdp": r.remittance_pct_gdp,
        "country_destination": r.country_destination,
        "ofw_count": r.ofw_count,
        "notes": r.notes,
    }


# ---------------------------------------------------------------------------
# extract() — public entry point
# ---------------------------------------------------------------------------

def extract() -> None:
    """
    Fetch all economic data sources and write to data/raw/economic/.

    Outputs:
      data/raw/economic/indicators.json   — list of EconomicIndicator dicts
      data/raw/economic/remittances.json  — list of OFWRemittance dicts

    Raises:
      RuntimeError — if both PSA and World Bank return zero records
                     (BSP CSV is optional — its absence is not an error)
    """
    cfg.ECONOMIC_RAW_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Economic extract: starting ...")

    indicators: list[dict] = []
    remittances: list[dict] = []

    # PSA — CPI monthly (lib/sources/psa returns CPIRecord, convert to EconomicIndicator dicts)
    logger.info("Economic extract: fetching PSA CPI ...")
    try:
        with PSAClient() as psa:
            cpi_records = psa.fetch_all()
        indicators.extend(_cpi_records_to_dicts(cpi_records))
        logger.info("PSA CPI: %d records converted.", len(indicators))
    except Exception as exc:
        logger.warning("PSA CPI fetch failed: %s", exc, exc_info=True)

    # World Bank — GDP, CPI annual, employment + OFW remittances
    logger.info("Economic extract: fetching World Bank indicators ...")
    try:
        with WorldBankClient() as wb:
            wb_indicators = wb.fetch_all_indicators()
            wb_remittances = wb.fetch_remittances()
        indicators.extend([_indicator_to_dict(r) for r in wb_indicators])
        remittances.extend([_remittance_to_dict(r) for r in wb_remittances])
        logger.info("World Bank: %d indicators, %d remittances.",
                    len(wb_indicators), len(wb_remittances))
    except Exception as exc:
        logger.warning("World Bank fetch failed: %s", exc, exc_info=True)

    # BSP CSV — optional monthly remittance enrichment
    bsp_csv_path = getattr(cfg, "BSP_REMITTANCE_CSV", None)
    if bsp_csv_path:
        bsp_records = _parse_bsp_csv(Path(bsp_csv_path))
        remittances.extend(bsp_records)

    if not indicators and not remittances:
        raise RuntimeError(
            "Economic extract: zero records from all sources. "
            "Check PSA OpenSTAT connectivity and World Bank API availability."
        )

    out_indicators = cfg.ECONOMIC_RAW_DIR / "indicators.json"
    out_remittances = cfg.ECONOMIC_RAW_DIR / "remittances.json"

    out_indicators.write_text(
        json.dumps(indicators, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    out_remittances.write_text(
        json.dumps(remittances, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    logger.info(
        "Economic extract complete: %d indicators, %d remittances → %s",
        len(indicators), len(remittances), cfg.ECONOMIC_RAW_DIR,
    )

    # ── Edge A: write lakehouse macro indicators if available ─────────────
    # Written AFTER the main extract so failure here never blocks core data.
    lakehouse_records = _try_lakehouse_macro()
    if lakehouse_records is not None:
        import pandas as pd
        lk_dir = cfg.ENRICHMENT_RAW_DIR
        lk_dir.mkdir(parents=True, exist_ok=True)
        lk_path = lk_dir / "lakehouse_macro.parquet"
        pd.DataFrame(
            [{"period": r.period, "indicator_code": r.indicator_code,
              "value": r.value, "source": r.source}
             for r in lakehouse_records]
        ).to_parquet(lk_path, index=False)
        logger.info("[economic] Lakehouse macro Parquet written: %s", lk_path)