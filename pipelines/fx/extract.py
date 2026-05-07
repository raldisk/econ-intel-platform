"""
FX extract — fetches BSP FX rates and Frankfurter fallback.

Sources:
  bsp_rerb     — BSP daily USD/PHP (day99_data.aspx)
  bsp_table12  — BSP monthly USD/PHP historical (tab12_pus.aspx)
  bsp_table13  — BSP cross rates vs PHP (tab13_php.aspx) — today's snapshot
  frankfurter  — Frankfurter API fallback if RERB unavailable

Raw output:
  data/raw/fx/fx_daily.json   — list of {rate_date, currency_pair, rate, source}
  data/raw/fx/fx_cross.json   — list of {rate_date, base_currency, php_rate, source}

Dependencies:
  httpx           (requirements.txt — already present)
  beautifulsoup4  (requirements.txt — added Phase 3 for BSP HTML parsing)

Interface contract:
    extract() -> None
    Raises RuntimeError if no daily rate obtained from any source.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Optional

import httpx
from bs4 import BeautifulSoup

import config as cfg

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ph-dashboard/1.0)"}
CROSS_CURRENCIES = ["EUR", "JPY", "GBP", "SGD", "AUD", "HKD", "CAD", "CNY"]


# ---------------------------------------------------------------------------
# Data classes — plain Python, no pydantic dependency
# ---------------------------------------------------------------------------

@dataclass
class FXRate:
    rate_date: str        # ISO date string for JSON serialisation
    currency_pair: str    # 'USD/PHP'
    rate: float
    source: str           # 'bsp_rerb' | 'bsp_table12' | 'frankfurter'


@dataclass
class CrossRate:
    rate_date: str
    base_currency: str
    php_rate: float
    source: str           # 'bsp_table13'


# ---------------------------------------------------------------------------
# HTTP helper — manual retry matching lib/sources/bsp.py pattern
# ---------------------------------------------------------------------------

def _get_html(client: httpx.Client, url: str) -> str:
    last_exc: Exception = RuntimeError("no attempts made")
    for attempt in range(1, cfg.HTTP_MAX_RETRIES + 1):
        try:
            resp = client.get(url, headers=_HEADERS)
            resp.raise_for_status()
            return resp.text
        except (httpx.HTTPError, httpx.TransportError) as exc:
            last_exc = exc
            logger.warning("FX GET attempt %d/%d [%s]: %s",
                           attempt, cfg.HTTP_MAX_RETRIES, url, exc)
            if attempt < cfg.HTTP_MAX_RETRIES:
                time.sleep(cfg.HTTP_BACKOFF_BASE ** attempt)
    raise last_exc


# ---------------------------------------------------------------------------
# BSP RERB — daily USD/PHP
# ---------------------------------------------------------------------------

def _parse_date(raw: str) -> Optional[date]:
    for fmt in ("%m/%d/%Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def fetch_bsp_daily(client: httpx.Client) -> Optional[FXRate]:
    """Fetch today's USD/PHP from BSP RERB page (most recent row)."""
    try:
        html = _get_html(client, cfg.BSP_RERB_URL)
    except Exception as exc:
        logger.warning("BSP RERB unavailable: %s", exc)
        return None

    soup = BeautifulSoup(html, "html.parser")
    for row in soup.select("table tr")[1:]:    # skip header row
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cells) < 2:
            continue
        rate_date = _parse_date(cells[0])
        if rate_date is None:
            continue
        try:
            rate_val = float(cells[1].replace(",", ""))
            return FXRate(
                rate_date=rate_date.isoformat(),
                currency_pair="USD/PHP",
                rate=round(rate_val, 4),
                source="bsp_rerb",
            )
        except ValueError:
            continue
    logger.warning("BSP RERB: no parseable row found in HTML table.")
    return None


# ---------------------------------------------------------------------------
# BSP Table 12 — monthly historical USD/PHP
# ---------------------------------------------------------------------------

def fetch_bsp_monthly(client: httpx.Client) -> list[FXRate]:
    """Fetch BSP Table 12 — monthly average USD/PHP from cfg.FX_START_YEAR."""
    try:
        html = _get_html(client, cfg.BSP_TABLE12_URL)
    except Exception as exc:
        logger.warning("BSP Table 12 unavailable: %s", exc)
        return []

    soup = BeautifulSoup(html, "html.parser")
    records: list[FXRate] = []
    month_names = ["Jan","Feb","Mar","Apr","May","Jun",
                   "Jul","Aug","Sep","Oct","Nov","Dec"]

    for row in soup.select("table tr"):
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if not cells:
            continue
        try:
            year = int(cells[0])
        except ValueError:
            continue
        if year < cfg.FX_START_YEAR:
            continue
        for i, _ in enumerate(month_names):
            if i + 1 >= len(cells):
                break
            raw = cells[i + 1].replace(",", "").strip()
            if not raw or raw == "-":
                continue
            try:
                records.append(FXRate(
                    rate_date=date(year, i + 1, 1).isoformat(),
                    currency_pair="USD/PHP",
                    rate=round(float(raw), 4),
                    source="bsp_table12",
                ))
            except ValueError:
                continue

    logger.info("BSP Table 12: %d monthly records (from %d).",
                len(records), cfg.FX_START_YEAR)
    return records


# ---------------------------------------------------------------------------
# BSP Table 13 — cross rates vs PHP
# ---------------------------------------------------------------------------

def fetch_bsp_cross(client: httpx.Client) -> list[CrossRate]:
    """Fetch BSP Table 13 — latest cross rates vs PHP."""
    try:
        html = _get_html(client, cfg.BSP_TABLE13_URL)
    except Exception as exc:
        logger.warning("BSP Table 13 unavailable: %s", exc)
        return []

    soup = BeautifulSoup(html, "html.parser")
    records: list[CrossRate] = []
    ref_date = date.today().isoformat()

    for row in soup.select("table tr"):
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cells) < 2:
            continue
        currency = cells[0].upper().strip()
        if currency not in CROSS_CURRENCIES:
            continue
        try:
            records.append(CrossRate(
                rate_date=ref_date,
                base_currency=currency,
                php_rate=round(float(cells[1].replace(",", "")), 4),
                source="bsp_table13",
            ))
        except ValueError:
            continue

    logger.info("BSP Table 13: %d cross rate records.", len(records))
    return records


# ---------------------------------------------------------------------------
# Frankfurter fallback — latest USD/PHP
# ---------------------------------------------------------------------------

def fetch_frankfurter_daily(client: httpx.Client) -> Optional[FXRate]:
    """Fetch latest USD/PHP from Frankfurter API as BSP fallback."""
    url = f"{cfg.FRANKFURTER_URL}/latest?from=USD&to=PHP"
    try:
        resp = client.get(url, timeout=httpx.Timeout(cfg.HTTP_TIMEOUT))
        resp.raise_for_status()
        data = resp.json()
        return FXRate(
            rate_date=data["date"],
            currency_pair="USD/PHP",
            rate=round(float(data["rates"]["PHP"]), 4),
            source="frankfurter",
        )
    except Exception as exc:
        logger.warning("Frankfurter fallback failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# extract() — public entry point
# ---------------------------------------------------------------------------

def extract() -> None:
    """
    Fetch all FX sources and write to data/raw/fx/.

    Priority:
      1. BSP RERB daily + Table 12 monthly historical + Table 13 cross rates.
      2. If RERB fails, Frankfurter provides the current daily rate.
      3. Raises RuntimeError if no daily rate is obtained from any source.

    Outputs:
      data/raw/fx/fx_daily.json  — list of FXRate dicts (daily + monthly)
      data/raw/fx/fx_cross.json  — list of CrossRate dicts
    """
    cfg.FX_RAW_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("FX extract: starting ...")

    daily_records: list[FXRate] = []
    cross_records: list[CrossRate] = []

    with httpx.Client(
        timeout=httpx.Timeout(cfg.HTTP_TIMEOUT),
        follow_redirects=True,
    ) as client:
        # Daily rate
        daily = fetch_bsp_daily(client)
        if daily:
            daily_records.append(daily)
            logger.info("FX RERB daily: %s — %.4f", daily.rate_date, daily.rate)
        else:
            logger.info("FX RERB unavailable — trying Frankfurter fallback ...")
            fallback = fetch_frankfurter_daily(client)
            if fallback:
                daily_records.append(fallback)
                logger.info("FX Frankfurter fallback: %s — %.4f",
                            fallback.rate_date, fallback.rate)

        # Historical monthly
        monthly = fetch_bsp_monthly(client)
        daily_records.extend(monthly)

        # Cross rates
        cross_records = fetch_bsp_cross(client)

    if not daily_records:
        raise RuntimeError(
            "FX extract: no records obtained from any source. "
            f"Check BSP_RERB_URL ({cfg.BSP_RERB_URL}) and Frankfurter connectivity."
        )

    daily_path = cfg.FX_RAW_DIR / "fx_daily.json"
    cross_path = cfg.FX_RAW_DIR / "fx_cross.json"

    daily_path.write_text(
        json.dumps([asdict(r) for r in daily_records], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    cross_path.write_text(
        json.dumps([asdict(r) for r in cross_records], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    logger.info(
        "FX extract complete: %d daily/monthly records, %d cross rates → %s",
        len(daily_records), len(cross_records), cfg.FX_RAW_DIR,
    )