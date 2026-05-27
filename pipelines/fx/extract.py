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
import httpx as _httpx  # prefixed to avoid clash with the httpx.Client used in BSP scrape

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
# Edge A: R2 lakehouse gold-layer adapter
#
# Data contract (R2 pipeline/contracts/gold_exchange_rates.yaml):
#   Columns: period (date), currency_pair (string), rate (double), source (string)
#   Format: long/tall — one row per (period, currency_pair) combination
#
# Mapping to R1 FXRate:
#   period       → rate_date (ISO string)
#   currency_pair → currency_pair (pass-through; e.g. "USD/PHP", "EUR/PHP")
#   rate         → rate (float)
#   source       → source (overridden to "macro_lakehouse" for lineage clarity)
#
# DDIA tradeoff: on ANY failure (network, timeout, bad status, malformed JSON)
# this function returns None and the caller falls back to BSP scrape.
# ---------------------------------------------------------------------------

def _try_lakehouse_fx() -> list[FXRate] | None:
    """
    Attempt to pull exchange rates from R2 gold layer.

    Returns list[FXRate] on success, None on any failure.
    Caller is responsible for fallback.
    """
    if not cfg.MACRO_LAKEHOUSE_URL:
        return None

    url = f"{cfg.MACRO_LAKEHOUSE_URL.rstrip('/')}/gold/gold_exchange_rates/data"
    try:
        resp = _httpx.get(url, timeout=cfg.MACRO_LAKEHOUSE_TIMEOUT)
        resp.raise_for_status()
        rows: list[dict] = resp.json()

        if not rows:
            logger.warning("[fx] Lakehouse returned 0 rows — falling back to BSP scrape.")
            return None

        rates = []
        skipped = 0
        for r in rows:
            try:
                rates.append(
                    FXRate(
                        rate_date=str(r["period"]),          # R2 contract: 'period' (date)
                        currency_pair=str(r["currency_pair"]),  # R2 contract: 'currency_pair'
                        rate=float(r["rate"]),               # R2 contract: 'rate' (double)
                        source="macro_lakehouse",            # Override for data lineage
                    )
                )
            except (KeyError, TypeError, ValueError) as row_exc:
                skipped += 1
                logger.debug("[fx] Skipped malformed lakehouse row: %s — %s", r, row_exc)

        if skipped:
            logger.warning("[fx] Skipped %d malformed rows from lakehouse.", skipped)

        if not rates:
            logger.warning("[fx] Lakehouse rows all malformed — falling back to BSP scrape.")
            return None

        logger.info("[fx] Lakehouse enrichment: %d FXRate records from R2.", len(rates))
        return rates

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[fx] Lakehouse unavailable (%s: %s) — falling back to BSP scrape.",
            type(exc).__name__,
            exc,
        )
        return None


# ---------------------------------------------------------------------------
# extract() — public entry point
# ---------------------------------------------------------------------------

def extract() -> None:
    """
    Pull FX rates. Attempts R2 lakehouse first; falls back to BSP scrape.

    Edge A integration: MACRO_LAKEHOUSE_URL absent or R2 unreachable → BSP scrape.
    No behavior change when MACRO_LAKEHOUSE_URL is unset.

    Priority:
      0. R2 lakehouse gold layer (if MACRO_LAKEHOUSE_URL is set and reachable).
      1. BSP RERB daily + Table 12 monthly historical + Table 13 cross rates.
      2. If RERB fails, Frankfurter provides the current daily rate.
      3. Raises RuntimeError if no daily rate is obtained from any source.

    Outputs:
      data/raw/fx/fx_daily.json  — list of FXRate dicts (daily + monthly)
      data/raw/fx/fx_cross.json  — list of CrossRate dicts
    """
    cfg.FX_RAW_DIR.mkdir(parents=True, exist_ok=True)

    # ── Edge A: attempt lakehouse gold layer ───────────────────────────────
    lakehouse_rates = _try_lakehouse_fx()
    if lakehouse_rates is not None:
        # Write to same output path as BSP scrape — downstream is transparent
        out = cfg.FX_RAW_DIR / "fx_daily.json"
        out.write_text(
            __import__("json").dumps(
                [__import__("dataclasses").asdict(r) for r in lakehouse_rates]
            ),
            encoding="utf-8",
        )
        logger.info("[fx] extract() complete via lakehouse: %d records.", len(lakehouse_rates))
        return
    # ── Fallback: existing BSP scrape unchanged below this line ───────────

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