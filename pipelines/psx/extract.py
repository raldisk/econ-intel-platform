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
