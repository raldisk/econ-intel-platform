"""
test_config.py — asserts config imports cleanly and all path roots are valid.

Run: pytest tests/test_config.py -v
"""
import sys
from pathlib import Path

# Project root on sys.path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import config as cfg


def test_root_is_absolute():
    assert cfg.ROOT.is_absolute()


def test_db_path_parent_is_under_root():
    assert str(cfg.DB_PATH).startswith(str(cfg.ROOT))


def test_schema_path_is_defined():
    # schema.sql location is declared — not necessarily present yet
    assert cfg.SCHEMA_PATH.suffix == ".sql"


def test_psx_tickers_nonempty():
    assert len(cfg.PSX_TICKERS) > 0


def test_psx_tickers_all_have_ps_suffix():
    for ticker in cfg.PSX_TICKERS:
        assert ticker.endswith(".PS"), f"Ticker missing .PS suffix: {ticker}"


def test_bsp_urls_are_https():
    for url in (cfg.BSP_KEY_RATE_URL, cfg.BSP_TABLE12_URL, cfg.BSP_TABLE13_URL):
        assert url.startswith("https://"), f"Non-HTTPS BSP URL: {url}"


def test_http_timeout_positive():
    assert cfg.HTTP_TIMEOUT > 0


def test_ttl_values_are_positive():
    assert cfg.TTL_PRICES > 0
    assert cfg.TTL_FX_LIVE > 0
    assert cfg.TTL_PSA > 0


def test_data_dirs_are_under_root():
    for path in (cfg.DATA_RAW, cfg.DATA_PROCESSED, cfg.DATA_CACHE):
        assert str(path).startswith(str(cfg.ROOT))