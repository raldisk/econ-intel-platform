"""
PSX extract — pulls OHLCV data for PSE-listed tickers via yfinance.

Writes one raw parquet per ticker to data/raw/psx/.
Uses incremental fetch: if a raw file already exists, only pulls
data from the last recorded date forward.

Data quality guards applied after every download:
  - Minimum 5 rows (skips tickers with suspiciously thin history)
  - Multi-level column header flattening (yfinance version quirk)
  - All-NaN Close detection (Yahoo Finance gap for illiquid tickers)
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf
import httpx as _httpx  # prefixed; used only in _enrich_with_psx_analytics

import config as cfg

logger = logging.getLogger(__name__)

# Minimum rows required before accepting a download as usable.
_MIN_ROWS = 5


def _raw_path(ticker: str) -> Path:
    return cfg.PSX_RAW_DIR / f"{ticker.replace('.', '_')}.parquet"


def _last_date(ticker: str) -> str:
    """
    Return the start date for incremental fetch.
    If raw file exists, returns (last_date + 1 day).
    Otherwise returns cfg.PSX_START_DATE.
    """
    path = _raw_path(ticker)
    if path.exists():
        try:
            existing = pd.read_parquet(path, columns=["Date"])
            last = pd.to_datetime(existing["Date"]).max()
            return (last + timedelta(days=1)).strftime("%Y-%m-%d")
        except Exception as exc:
            logger.warning("Could not read last date for %s: %s — full fetch.", ticker, exc)
    return cfg.PSX_START_DATE


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def _quality_check(df: pd.DataFrame, ticker: str) -> bool:
    if df.empty:
        logger.warning("[%s] No data returned by yfinance — skipping.", ticker)
        return False

    if len(df) < _MIN_ROWS:
        logger.warning("[%s] Suspiciously few rows (%d < %d) — skipping.", ticker, len(df), _MIN_ROWS)
        return False

    if "Close" not in df.columns:
        logger.warning("[%s] 'Close' column missing — skipping.", ticker)
        return False

    if df["Close"].isna().all():
        logger.warning("[%s] All Close prices are NaN — skipping.", ticker)
        return False

    return True


# ---------------------------------------------------------------------------
# Edge B: psx-equity-analytics (R4) optional enrichment adapter
#
# Enrichment columns from R4 GET /analytics/daily:
#   vwap (float)               — Volume-Weighted Average Price [NON-ADDITIVE]
#   amihud_illiquidity (float) — |daily_return| / daily_volume
#   price_impact_bps (float)   — Amihud in basis points (derived)
#   trend_component (float)    — SARIMA trend decomposition
#   sarima_status (string)     — OK | FAILED_CONVERGENCE | INSUFFICIENT_DATA | SKIPPED_NO_STATSMODELS
#
# Kimball note: vwap is non-additive across time. Summing VWAP across days
# is semantically wrong. VIEW_AXIS_HINTS carries a warning for dashboard authors.
#
# Design: enrichment is a post-pass after yfinance download. Enrichment failure
# for a single ticker does NOT affect other tickers.
# ---------------------------------------------------------------------------

_ENRICHMENT_COLS = [
    "vwap", "amihud_illiquidity", "price_impact_bps",
    "trend_component", "sarima_status",
]


def _enrich_with_psx_analytics(
    df: pd.DataFrame,
    ticker: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """
    Attempt to add R4 analytics columns to a single-ticker DataFrame.

    Args:
        df: DataFrame with at least 'Date' and 'ticker' columns.
        ticker: PSX ticker symbol (e.g. 'SM.PS').
        start_date: ISO date string for query range start.
        end_date: ISO date string for query range end.

    Returns:
        Original df with analytics columns merged on Date, or original df
        unchanged if PSX_ANALYTICS_API_URL is unset or R4 is unreachable.
    """
    if not cfg.PSX_ANALYTICS_API_URL:
        return df  # enrichment disabled — caller gets OHLCV-only frame

    try:
        resp = _httpx.get(
            f"{cfg.PSX_ANALYTICS_API_URL.rstrip('/')}/analytics/daily",
            params={"symbol": ticker, "start_date": start_date, "end_date": end_date},
            timeout=cfg.PSX_ANALYTICS_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
        rows = payload.get("data", []) if isinstance(payload, dict) else payload

        if not rows:
            logger.debug("[psx] No analytics rows returned for %s.", ticker)
            return df

        enrichment = pd.DataFrame(rows)
        # R4 returns 'session_date' for the date column — normalise to 'Date'
        if "session_date" in enrichment.columns:
            enrichment = enrichment.rename(columns={"session_date": "Date"})
        elif "date" in enrichment.columns:
            enrichment = enrichment.rename(columns={"date": "Date"})
        else:
            logger.warning("[psx] R4 response for %s has no recognisable date column.", ticker)
            return df

        # Keep only the date key + enrichment columns (guard against schema drift)
        available_cols = ["Date"] + [c for c in _ENRICHMENT_COLS if c in enrichment.columns]
        enrichment = enrichment[available_cols].copy()

        merged = df.merge(enrichment, on="Date", how="left")
        logger.debug(
            "[psx] Analytics enrichment for %s: %d date(s) matched.",
            ticker,
            merged[_ENRICHMENT_COLS[0]].notna().sum() if _ENRICHMENT_COLS[0] in merged.columns else 0,
        )
        return merged

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[psx] Analytics enrichment failed for %s (%s: %s) — "
            "OHLCV-only data retained for this ticker.",
            ticker, type(exc).__name__, exc,
        )
        return df


def extract() -> None:
    """
    Pull OHLCV from yfinance for all configured PSX tickers.
    Writes/appends raw parquet files to data/raw/psx/.
    Tolerates individual ticker failures — logs and continues.
    """
    cfg.PSX_RAW_DIR.mkdir(parents=True, exist_ok=True)

    # --- SEED FALLBACK (DEBUG MODE) ---
    seed_path = cfg.PSX_RAW_DIR / "seed_psx.csv"

    if seed_path.exists():
        logger.warning("Using seed data fallback (yfinance bypassed)")

        df = pd.read_csv(seed_path, sep=None, engine="python")

        # normalize column names
        df.columns = [c.encode("utf-8").decode("utf-8-sig").strip().lower() for c in df.columns]

        # validate required columns in the seed file
        required = {"date", "ticker", "open", "high", "low", "close", "volume"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Seed CSV missing required columns: {missing}")

        # convert and rename to match the transform step's expected schema
        df["date"] = pd.to_datetime(df["date"])
        df = df.rename(columns={
            "date": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        })

        # keep the expected raw-parquet column order
        df = df[["Date", "ticker", "Open", "High", "Low", "Close", "Volume"]]

        path = _raw_path("JFC")
        df.to_parquet(path, index=False)

        logger.info("Seed data loaded → %s", path)
        return
    # --- END SEED FALLBACK ---


    # Safe ticker list (handles missing PSX_INDEX_TICKER)
    tickers = []
    index_ticker = getattr(cfg, "PSX_INDEX_TICKER", None)
    if index_ticker:
        tickers.append(index_ticker)
    tickers.extend(cfg.PSX_TICKERS)

    today = date.today().strftime("%Y-%m-%d")

    # Track successful downloads
    success_count = 0

    for ticker in tickers:
        start = _last_date(ticker)

        if start >= today:
            logger.info("[%s] Already up to date — skipping.", ticker)
            continue

        logger.info("[%s] Fetching %s → %s ...", ticker, start, today)

        try:
            df: pd.DataFrame = yf.download(
                ticker,
                start=start,
                end=today,
                auto_adjust=True,
                progress=False,
            )

            df = _flatten_columns(df)

            if not _quality_check(df, ticker):
                continue

            success_count += 1

            df.reset_index(inplace=True)
            df["ticker"] = ticker

            # ── Edge B: attempt analytics enrichment (non-fatal) ──────────
            df = _enrich_with_psx_analytics(df, ticker, cfg.PSX_START_DATE, today)
            # ── End Edge B enrichment ──────────────────────────────────────

            path = _raw_path(ticker)

            if path.exists():
                existing = pd.read_parquet(path)
                existing = _flatten_columns(existing)

                df = pd.concat([existing, df], ignore_index=True)
                df.drop_duplicates(subset=["Date", "ticker"], keep="last", inplace=True)
                df.sort_values("Date", inplace=True)

            df.to_parquet(path, index=False)

            logger.info("[%s] Saved %d rows → %s", ticker, len(df), path)

        except Exception as exc:
            logger.error("[%s] Extract failed: %s", ticker, exc)

    if success_count == 0:
        raise RuntimeError("PSX extract produced no usable data from any ticker.")
