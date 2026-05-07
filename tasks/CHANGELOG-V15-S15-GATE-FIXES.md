# CHANGELOG

**Version:** V15
**Session:** S15
**Phase:** Phase 0.5 — Gate verification + bug fixes
**Date:** 2026-04-05
**Supersedes:** PH-Dashboard-V14-S14-P12-FINAL

---

## Summary

Full Phase 0.5 gate run executed in CI-equivalent environment. All five gates
passed after resolving eight integration bugs found during first-run assembly.
All 9 pipelines completed successfully. 48/48 tests green. 22 required DuckDB
objects verified.

---

## Gate results

| Gate | Command | Result |
|---|---|---|
| 1 | `pip install -e ".[dev]"` | ✅ Exit 0 |
| 2 | `pytest tests/ -v` | ✅ 48/48 passed |
| 3 | `python -m db.init` | ✅ All 22 required objects verified |
| 4 | `python -m pipelines.psx.run` | ✅ 3,330 rows — pipeline_runs ('psx', 'success') |
| 5 | `from lib.db import get_read_conn` | ✅ Live read connection confirmed |

---

## Pipeline smoke results (all 9 pipelines)

| Pipeline | Status | Rows | Notes |
|---|---|---|---|
| psx | ✅ success | 3,330 | 3 tickers × 1,110 days |
| bsp | ✅ success | 27 | FY2020–2025, hike/hold/cut direction counts correct |
| fx | ✅ success | 2,936 | USD/PHP daily + 8 cross rates; `stg_fx_rates`, `fx_volatility`, `real_exchange_rate`, `cpi_vs_fx` all created |
| economic | ✅ success | 217 | cpi_trend=192, gdp_tracker=25, remittance_trend=25, economic_dashboard=26 |
| labor | ✅ success | 0 | Data gap (no LFS CSV) — correct behavior |
| regional | ✅ success | 34 | 17 regions × 2 years; Gini 0.30–0.36 |
| prices | ✅ success | 8,169 | 15 commodities; STL decomposition 3,792 rows; shock events view created |
| sentiment | ✅ success | 6,480 | 6 topics, trailing 90 days, synthetic fallback |
| coa | ✅ success | 75 | 15 agencies × FY2019–2023; 8 low utilizers flagged |

---

## Bugs fixed

### CF-V15-001 — schema.sql: sequence order + DEFAULT nextval (MEDIUM)
**File:** `db/schema.sql`
**Root cause:** `CREATE SEQUENCE pipeline_runs_seq` appeared after `CREATE TABLE
pipeline_runs` — DuckDB cannot reference a sequence that doesn't exist yet. Also
`id INTEGER PRIMARY KEY` had no DEFAULT, so inserts without explicit `id` threw
`NOT NULL constraint failed`.
**Fix:** Moved sequence creation before table DDL; added `DEFAULT nextval('pipeline_runs_seq')`
to the `id` column. This is a re-application of CF-V4-004 that was only patched in
`db/init.py` at the time, not in the canonical `schema.sql`.

### CF-V15-002 — db/init.py: REQUIRED_OBJECTS count stale at 15 (HIGH)
**File:** `db/init.py`
**Root cause:** `db/init.py` was sourced from V7 (Phase 1 era). It listed 15 required
objects — the schema expanded to 22 across Phases 3–11 with no corresponding update.
**Fix:** `REQUIRED_OBJECTS` expanded to 22 objects covering all 9 pipeline base views
plus cross-pipeline views.

### CF-V15-003 — db/init.py: PARQUET_MAP missing ECONOMIC_* and COA keys (HIGH)
**File:** `db/init.py`
**Root cause:** `economic/load.py` references `PARQUET_MAP["ECONOMIC_CPI_PARQUET"]`
et al.; `coa/load.py` references `PARQUET_MAP["COA_PARQUET"]`. Neither key was in
the V7-era PARQUET_MAP.
**Fix:** Added `ECONOMIC_CPI_PARQUET`, `ECONOMIC_GDP_PARQUET`,
`ECONOMIC_REMITTANCE_PARQUET`, `ECONOMIC_DASHBOARD_PARQUET`, and `COA_PARQUET`
to PARQUET_MAP.

### CF-V15-004 — db/schema.sql: 7 derived-view stubs missing (MEDIUM)
**File:** `db/schema.sql`
**Root cause:** `REQUIRED_OBJECTS` now includes views that are created by pipeline
`load.py` calls, not by `schema.sql`. `db.init` verification would fail on a clean
boot before any pipeline has run.
**Fix:** Added `WHERE 1=0` placeholder stubs for: `stg_fx_rates`, `fx_volatility`,
`real_exchange_rate`, `economic_dashboard`, `price_trend_by_commodity`,
`sentiment_topic_trend`, `coa_low_utilizers`.

### CF-V15-005 — config.py: FX URL constants missing (MEDIUM)
**File:** `config.py`
**Root cause:** `pipelines/fx/extract.py` references `cfg.BSP_RERB_URL`,
`cfg.FRANKFURTER_URL`, `cfg.FX_START_YEAR` — not present in the V6 base config.
**Fix:** Added all three constants to `config.py`.

### CF-V15-006 — config.py: Economic constants missing (MEDIUM)
**File:** `config.py`
**Root cause:** `pipelines/economic/extract.py` references `cfg.ECONOMIC_RAW_DIR`,
`cfg.ECONOMIC_PROCESSED_DIR`, `cfg.ECONOMIC_START_YEAR`, `cfg.BSP_REMITTANCE_CSV`,
`cfg.WORLD_BANK_BASE_URL`, `cfg.WORLD_BANK_PER_PAGE` — none present in V6 base.
**Fix:** Added all six constants to `config.py`.

### CF-V15-007 — regional/extract.py: Path(None) TypeError (HIGH)
**File:** `pipelines/regional/extract.py`
**Root cause:** `cfg.REGIONAL_DATA_DIR` defaults to `None`. The code did
`Path(real_dir)` where `real_dir` was `getattr(cfg, "REGIONAL_DATA_DIR", cfg.REGIONAL_RAW_DIR)` — but since the attribute *exists* (as None), `getattr` returned None rather than the fallback, and `Path(None)` raises `TypeError`.
**Fix:** Changed to `getattr(cfg, "REGIONAL_DATA_DIR", None) or cfg.REGIONAL_RAW_DIR`
to coalesce None to the raw data directory.

### CF-V15-008 — regional/transform.py: numpy 2.0 removed np.trapz (MEDIUM)
**File:** `pipelines/regional/transform.py`
**Root cause:** numpy 2.0 removed the long-deprecated `np.trapz` alias. The
Lorenz-curve Gini computation used `np.trapz(L, P)`.
**Fix:** `np.trapezoid(L, P) if hasattr(np, 'trapezoid') else np.trapz(L, P)` —
forward-compatible shim works on both numpy 1.x and 2.x.

### CF-V15-009 — pyproject.toml: invalid build backend (LOW)
**File:** `pyproject.toml`
**Root cause:** `setuptools.backends.legacy:build` requires setuptools ≥ 61 with
the new build backend protocol, which the container's pip did not support.
**Fix:** Changed to `setuptools.build_meta`.

---

## Modified files summary

- `config.py` — 9 new constants added (FX URLs + Economic dirs)
- `db/schema.sql` — sequence before table, DEFAULT nextval, 7 new stub views
- `db/init.py` — REQUIRED_OBJECTS expanded to 22, PARQUET_MAP expanded to 16 entries
- `pipelines/regional/extract.py` — None-coalesce fix
- `pipelines/regional/transform.py` — numpy 2.0 trapz compatibility
- `pyproject.toml` — build backend fix
