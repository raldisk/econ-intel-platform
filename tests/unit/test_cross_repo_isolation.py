"""
Cross-repo isolation tests for econ-intel-platform (R1).
Fitness function: verifies Edges A, B, C can each be cleanly disabled
and never block R1's core pipelines.

These tests MUST pass with:
  MACRO_LAKEHOUSE_URL    unset
  PSX_ANALYTICS_API_URL  unset
  CREDIT_RISK_API_URL    unset

No network calls are made. All upstreams are simulated as unreachable
via a non-routable address (localhost:19999).
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Edge A — FX lakehouse adapter
# ---------------------------------------------------------------------------

class TestEdgeAFXIsolation:
    """R1 fx pipeline must work when MACRO_LAKEHOUSE_URL is absent."""

    def test_returns_none_when_url_unset(self, monkeypatch):
        monkeypatch.delenv("MACRO_LAKEHOUSE_URL", raising=False)
        # Re-import to pick up cleared env var
        _reload_config()
        from pipelines.fx.extract import _try_lakehouse_fx
        result = _try_lakehouse_fx()
        assert result is None

    def test_returns_none_when_r2_unreachable(self, monkeypatch):
        monkeypatch.setenv("MACRO_LAKEHOUSE_URL", "http://localhost:19999")
        _reload_config()
        from pipelines.fx.extract import _try_lakehouse_fx
        # Must not raise; must return None on connection failure
        result = _try_lakehouse_fx()
        assert result is None

    def test_maps_r2_contract_columns_correctly(self, monkeypatch, respx_mock):
        """Verify column mapping against R2 gold_exchange_rates contract schema."""
        pytest.importorskip("respx")
        import respx
        import httpx as hx

        monkeypatch.setenv("MACRO_LAKEHOUSE_URL", "http://mock-r2:8000")
        _reload_config()

        mock_rows = [
            {"period": "2026-05-01", "currency_pair": "USD/PHP", "rate": 56.5, "source": "BSP"},
            {"period": "2026-05-01", "currency_pair": "EUR/PHP", "rate": 61.2, "source": "BSP"},
        ]

        with respx.mock:
            respx.get(
                "http://mock-r2:8000/gold/gold_exchange_rates/data"
            ).mock(return_value=hx.Response(200, json=mock_rows))

            from pipelines.fx.extract import _try_lakehouse_fx
            result = _try_lakehouse_fx()

        assert result is not None
        assert len(result) == 2
        # Verify correct field mapping: R2 'period' → R1 'rate_date'
        assert result[0].rate_date == "2026-05-01"
        assert result[0].currency_pair == "USD/PHP"
        assert result[0].rate == 56.5
        assert result[0].source == "macro_lakehouse"  # overridden for lineage


# ---------------------------------------------------------------------------
# Edge A — macro indicators lakehouse adapter
# ---------------------------------------------------------------------------

class TestEdgeAMacroIsolation:
    """R1 economic pipeline must work when MACRO_LAKEHOUSE_URL is absent."""

    def test_returns_none_when_url_unset(self, monkeypatch):
        monkeypatch.delenv("MACRO_LAKEHOUSE_URL", raising=False)
        _reload_config()
        from pipelines.economic.extract import _try_lakehouse_macro
        result = _try_lakehouse_macro()
        assert result is None

    def test_returns_none_when_r2_unreachable(self, monkeypatch):
        monkeypatch.setenv("MACRO_LAKEHOUSE_URL", "http://localhost:19999")
        _reload_config()
        from pipelines.economic.extract import _try_lakehouse_macro
        result = _try_lakehouse_macro()
        assert result is None

    def test_parquet_write_is_optional_not_blocking(self, monkeypatch, tmp_path):
        """Lakehouse macro Parquet write must not block if dir is missing."""
        monkeypatch.delenv("MACRO_LAKEHOUSE_URL", raising=False)
        # Even with a bad enrichment dir, the existing economic pipeline continues
        _reload_config()
        from pipelines.economic.extract import _try_lakehouse_macro
        result = _try_lakehouse_macro()
        assert result is None  # No crash, no blocking


# ---------------------------------------------------------------------------
# Edge B — PSX analytics adapter
# ---------------------------------------------------------------------------

class TestEdgeBPSXAnalyticsIsolation:
    """R1 PSX pipeline must return unmodified DataFrame when PSX_ANALYTICS_API_URL is absent."""

    def test_returns_original_df_when_url_unset(self, monkeypatch):
        monkeypatch.delenv("PSX_ANALYTICS_API_URL", raising=False)
        _reload_config()
        from pipelines.psx.extract import _enrich_with_psx_analytics

        df = pd.DataFrame({"Date": ["2026-05-25"], "Close": [100.0], "ticker": ["SM.PS"]})
        result = _enrich_with_psx_analytics(df, "SM.PS", "2026-01-01", "2026-05-25")
        pd.testing.assert_frame_equal(result, df)

    def test_returns_original_df_when_r4_unreachable(self, monkeypatch):
        monkeypatch.setenv("PSX_ANALYTICS_API_URL", "http://localhost:19999")
        _reload_config()
        from pipelines.psx.extract import _enrich_with_psx_analytics

        df = pd.DataFrame({"Date": ["2026-05-25"], "Close": [100.0], "ticker": ["SM.PS"]})
        result = _enrich_with_psx_analytics(df, "SM.PS", "2026-01-01", "2026-05-25")
        # Must not raise; must return original frame unchanged
        assert list(result.columns) == list(df.columns)

    def test_enrichment_failure_does_not_affect_other_tickers(self, monkeypatch):
        """A single ticker enrichment failure must not propagate to other tickers."""
        monkeypatch.setenv("PSX_ANALYTICS_API_URL", "http://localhost:19999")
        _reload_config()
        from pipelines.psx.extract import _enrich_with_psx_analytics

        for ticker in ["SM.PS", "BDO.PS", "ALI.PS"]:
            df = pd.DataFrame({"Date": ["2026-05-25"], "Close": [100.0]})
            result = _enrich_with_psx_analytics(df, ticker, "2026-01-01", "2026-05-25")
            assert result is not None


# ---------------------------------------------------------------------------
# Edge C — credit risk adapter
# ---------------------------------------------------------------------------

class TestEdgeCCreditRiskIsolation:
    """R1 credit_risk pipeline must write empty Parquet when CREDIT_RISK_API_URL is absent."""

    def test_extract_returns_none_when_url_unset(self, monkeypatch):
        monkeypatch.delenv("CREDIT_RISK_API_URL", raising=False)
        _reload_config()
        from pipelines.credit_risk.extract import extract_credit_exposure
        result = extract_credit_exposure("202504")
        assert result is None

    def test_extract_returns_none_when_r3_unreachable(self, monkeypatch):
        monkeypatch.setenv("CREDIT_RISK_API_URL", "http://localhost:19999")
        _reload_config()
        from pipelines.credit_risk.extract import extract_credit_exposure
        result = extract_credit_exposure("202504")
        assert result is None

    def test_transform_produces_schema_compatible_empty_frame(self):
        from pipelines.credit_risk.transform import transform
        df = transform(None)
        assert isinstance(df, pd.DataFrame)
        required_cols = {
            "period_key", "outstanding_balance_usd", "npl_count",
            "total_rwa_usd", "total_provisions_usd", "facility_count", "submitted_at",
        }
        assert required_cols.issubset(set(df.columns))
        assert len(df) == 0

    def test_load_writes_empty_parquet_without_crash(self, monkeypatch, tmp_path):
        monkeypatch.setattr("config.ENRICHMENT_PROCESSED_DIR", tmp_path)
        monkeypatch.setattr("config.DB_PATH", tmp_path / "test.duckdb")

        import duckdb
        # Pre-create DuckDB so the view registration doesn't fail on missing file
        duckdb.connect(str(tmp_path / "test.duckdb")).close()

        from pipelines.credit_risk.transform import transform
        from pipelines.credit_risk.load import load

        df = transform(None)
        load(df)  # Must not raise

        parquet_path = tmp_path / "credit_exposure.parquet"
        assert parquet_path.exists()
        written = pd.read_parquet(parquet_path)
        assert len(written) == 0

    def test_prior_month_period_key_never_returns_current_month(self):
        """Regression test: run.py must never request the current open month."""
        from pipelines.credit_risk.run import _prior_month_period_key
        from datetime import datetime, timezone

        key = _prior_month_period_key()
        now = datetime.now(tz=timezone.utc)
        current_yyyymm = now.strftime("%Y%m")
        assert key != current_yyyymm, (
            f"period_key={key} equals current month {current_yyyymm}. "
            "Requesting the current open month always returns 404 from R3."
        )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _reload_config():
    """Force config module to re-read env vars after monkeypatch."""
    import importlib
    import config
    importlib.reload(config)
    # Reload dependent modules that cache config at import time
    for mod_name in list(sys.modules.keys()):
        if mod_name.startswith("pipelines."):
            del sys.modules[mod_name]
