"""
test_schema_bootstrap.py — runs schema.sql against an in-memory DuckDB instance
and asserts all required objects are registered.

Does NOT touch duckdb_local.db. Safe to run at any time.

Run: pytest tests/test_schema_bootstrap.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import config as cfg

# Required objects match db/init.py::REQUIRED_OBJECTS.
REQUIRED_VIEWS = {
    "psx_prices",
    "bsp_policy_rate",
    "fx_rates",
    "gdp_tracker",
    "cpi_trend",
    "remittance_trend",
    "labor_market",
    "regional_inequality",
    "commodity_prices",
    "food_price_decomposition",
    "social_sentiment",
    "coa_budget_utilization",
    "psx_vs_bsp",
    "cpi_vs_fx",
    # staging views
    "stg_gdp",
    "stg_cpi",
    "stg_remittances",
    # PATCH FINDING-006: add the 7 objects present in db/init.py::REQUIRED_OBJECTS
    # but absent from this test set.  A schema.sql regression dropping any of
    # these would pass the test but fail init_db() at runtime.
    "stg_fx_rates",
    "fx_volatility",
    "real_exchange_rate",
    "economic_dashboard",
    "price_trend_by_commodity",
    "sentiment_topic_trend",
    "coa_low_utilizers",
}

REQUIRED_TABLES = {
    "pipeline_runs",
}


@pytest.fixture(scope="module")
def mem_con():
    """
    In-memory DuckDB connection with schema.sql applied.
    Yields the connection; closes after tests complete.
    """
    schema_path = cfg.ROOT / "db" / "schema.sql"
    if not schema_path.exists():
        pytest.skip(f"schema.sql not found at {schema_path}")

    sql = schema_path.read_text(encoding="utf-8")

    # schema.sql uses placeholder pattern (WHERE 1=0) — no parquet paths needed.
    # Execute directly against in-memory DB.
    con = duckdb.connect(":memory:")
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    for stmt in statements:
        try:
            con.execute(stmt)
        except Exception as exc:
            con.close()
            pytest.fail(f"Schema statement failed:\n{stmt[:200]}\nError: {exc}")

    yield con
    con.close()


def _registered(con: duckdb.DuckDBPyConnection) -> set[str]:
    rows = con.execute(
        "SELECT LOWER(table_name) FROM information_schema.tables"
    ).fetchall()
    return {r[0] for r in rows}


def test_all_required_views_registered(mem_con):
    registered = _registered(mem_con)
    missing = REQUIRED_VIEWS - registered
    assert not missing, f"Missing views after bootstrap: {sorted(missing)}"


def test_pipeline_runs_table_registered(mem_con):
    registered = _registered(mem_con)
    missing = REQUIRED_TABLES - registered
    assert not missing, f"Missing tables after bootstrap: {sorted(missing)}"


def test_psx_prices_has_expected_columns(mem_con):
    """psx_prices placeholder must expose the correct column schema."""
    cols = {
        row[0].lower()
        for row in mem_con.execute("DESCRIBE psx_prices").fetchall()
    }
    expected = {
        "date", "ticker", "open", "high", "low", "close",
        "volume", "pct_change", "rsi_14", "ma_20", "ma_50",
        "ma_signal", "volume_zscore",
    }
    assert expected <= cols, f"psx_prices missing columns: {expected - cols}"


def test_bsp_policy_rate_has_expected_columns(mem_con):
    cols = {
        row[0].lower()
        for row in mem_con.execute("DESCRIBE bsp_policy_rate").fetchall()
    }
    expected = {"decision_date", "overnight_rp", "overnight_srp", "direction"}
    assert expected <= cols, f"bsp_policy_rate missing columns: {expected - cols}"


def test_psx_prices_is_empty_on_first_boot(mem_con):
    """Placeholder view must return zero rows — not crash."""
    count = mem_con.execute("SELECT COUNT(*) FROM psx_prices").fetchone()[0]
    assert count == 0, f"Expected 0 rows from placeholder, got {count}"


def test_pipeline_runs_accepts_insert(mem_con):
    """pipeline_runs table must accept inserts — used by every load.py."""
    mem_con.execute(
        "INSERT INTO pipeline_runs (pipeline, status, rows_affected) VALUES ('test', 'success', 0)"
    )
    count = mem_con.execute(
        "SELECT COUNT(*) FROM pipeline_runs WHERE pipeline = 'test'"
    ).fetchone()[0]
    assert count == 1


def test_psx_vs_bsp_view_exists_and_selectable(mem_con):
    """Cross-analysis view must be selectable even when source views are empty."""
    # Both psx_prices and bsp_policy_rate are empty stubs — ASOF JOIN on empty
    # tables should return zero rows, not raise.
    try:
        count = mem_con.execute("SELECT COUNT(*) FROM psx_vs_bsp").fetchone()[0]
        assert count == 0
    except Exception as exc:
        pytest.fail(f"psx_vs_bsp raised on empty source views: {exc}")


def test_coa_budget_utilization_is_placeholder(mem_con):
    """COA view must be a zero-row placeholder — not backed by a real parquet."""
    count = mem_con.execute("SELECT COUNT(*) FROM coa_budget_utilization").fetchone()[0]
    assert count == 0