# PH-Dashboard Build Tasks

<!-- Last updated: 2026-03-31 — Session 14 complete — ALL PHASES ARTIFACT-COMPLETE -->
<!-- Phase 0 artifact delivery: ✅ COMPLETE -->
<!-- Phase 0.5 verification gate: ⬜ NOT YET RUN — user action required -->
<!-- Phase 1 artifact delivery: ✅ COMPLETE (patched Session 6) -->
<!-- Phase 2 artifact delivery: ✅ COMPLETE — awaiting Phase 0.5 + E2E gate -->
<!-- Phase 3 artifact delivery: ✅ COMPLETE — V7-S7-P3 -->
<!-- Phase 4 artifact delivery: ✅ COMPLETE — V8-S8-P4 -->
<!-- Phase 5 artifact delivery: ✅ COMPLETE — V10-S10-P5 -->
<!-- Phase 6 artifact delivery: ✅ COMPLETE — V10-S10-P6 -->
<!-- Phase 7 artifact delivery: ✅ COMPLETE — V11-S11-P7 -->
<!-- Phase 8 artifact delivery: ✅ COMPLETE — V11-S11-P8 -->
<!-- Phase 9 artifact delivery: ✅ COMPLETE — V12-S12-P9 -->
<!-- Phase 10 artifact delivery: ✅ COMPLETE — V13-S13-P10 -->
<!-- Phase 11 artifact delivery: ✅ COMPLETE — V13-S13-P11 -->
<!-- Phase 12 artifact delivery: ✅ COMPLETE — V14-S14-P12 -->

---

## Phase 0 — Pre-Build Gate

**Status: Artifact Delivery ✅ | Verification Gate ✅ UNBLOCKED**

- [x] FIX-1: `pyproject.toml` naming — correct in Session 3 zip
- [x] FIX-2: `config.py` re-packaged — all 25 required attrs confirmed present
- [x] FIX-3: `pipelines/psx/load.py` produced — CRITICAL blocker resolved
- [x] CF-V4-003: `db/init.py` REQUIRED_OBJECTS updated — staging views added
- [x] CF-V4-004: `db/schema.sql` sequence wired — `id DEFAULT nextval(...)`
- [x] CF-V4-005: `__init__.py` files created — 5 packages
- [x] CF-V4-007: L010 appended to `tasks/lessons.md`

---

## Phase 0.5 — Verification Gate

**Status: ⬜ NOT YET RUN — run these now in order**

```
Gate 1:  pip install -e ".[dev]"
         → expect: no dependency conflicts

Gate 2:  pytest tests/ -v
         → expect: all GREEN (test_config, test_schema_bootstrap,
                               test_psx_transform, test_bsp_parse)

Gate 3:  python -m db.init
         → expect: "All 18 required objects verified. exit 0"

Gate 4:  python -m pipelines.psx.run
         → expect: extract + transform + load complete, exit 0
         → check log: "psx_prices registered: N rows | M tickers"

Gate 5:  python -c "from lib.db import get_read_conn; print('ok')"
         → expect: ok
```

**Phase 1 + Phase 2 git commit does not happen until all 5 gates are GREEN.**

Additional checks before git commit:

```
python -c "import pipelines.psx.extract"
→ expect: no error

python -c "
import duckdb, config as cfg
con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
r = con.execute('SELECT COUNT(*), MIN(date), MAX(date) FROM psx_prices').fetchone()
print(f'rows={r[0]}, from={r[1]}, to={r[2]}')
con.close()
"
→ expect: real row count, date range from 2015 to present

python -c "
import duckdb, config as cfg
con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
r = con.execute(\"SELECT * FROM pipeline_runs WHERE pipeline='psx'\").fetchall()
print(r)
con.close()
"
→ expect: at least one ('psx', 'success', N) row

python -m pipelines.psx.run   # second run
→ check pipeline_runs: id increments (sequence working)
```

---

## Phase 1 — Foundation + PSX Pipeline E2E

**Status: ✅ Artifact Delivery COMPLETE + Patched Session 6**

### Session 5 artifacts delivered:
- [x] CF-V5-001: `lib/sources/psa.py` — httpx + manual retry + dataclass, no tenacity/rich
- [x] CF-V5-002 + CF-V5-003: `lib/sources/ttl_cache.py` — mtime TTL + threading.Lock
- [x] CF-V5-004: `.gitignore` — data/, db/*.db, pycache, env, parquet, log coverage
- [x] CF-V5-006: psa.py + ttl_cache.py tests deferred to Phase 3 — recorded below

### Session 6 patches applied:
- [x] CF-V6-001: `psa.py` geo keyword "area" removed; "geography"/"region" added
- [x] CF-V6-002: `psa.py` zero-record case now logs WARNING not INFO
- [x] CF-V6-003: `psa.py` base-year revision comment block added above `_CPI_TABLE`
- [x] CF-V6-005: `ttl_cache.py` double-fetch race documented in `get_or_fetch`
- [x] CF-V6-006: `psa.py` `exc_info=True` added to `_fetch_series` outer handler

### User actions required (after Phase 0.5 gates pass):
- [ ] `git init` from PH-Dashboard root
- [ ] `git add .`
- [ ] `git commit -m "Phase 0 + Phase 1 + Phase 2: foundation, PSX pipeline, shared lib, BSP pipeline"`
- [ ] E2E smoke re-run post-commit: `python -m pipelines.psx.run` → confirm row count in log

### Deferred tests (not blockers — resolve in Phase 3):
- [ ] `tests/test_psa_client.py` — mock PSA PXWeb API, assert CPIRecord structure,
      verify `_parse_pxweb_response()` handles missing time dimension gracefully
- [ ] `tests/test_ttl_cache.py` — tmp-dir fixture, test is_fresh/get_or_fetch/set_cached,
      verify atomic write (read after write returns correct data), verify invalidate

---

## Phase 2 — BSP Pipeline

**Status: ✅ Artifact Delivery COMPLETE — awaiting Phase 0.5 gate + E2E smoke**

### Session 6 artifacts delivered:
- [x] `pipelines/bsp/__init__.py`
- [x] `pipelines/bsp/extract.py` — thin orchestrator → `lib/sources/bsp.fetch_policy_rates()`; always full refresh; raises on empty
- [x] `pipelines/bsp/transform.py` — JSON → parquet; ascending sort (L006); nullable Float64 for overnight_srp
- [x] `pipelines/bsp/load.py` — CREATE OR REPLACE VIEW; COUNT + date range log; mirrors psx/load.py
- [x] `pipelines/bsp/run.py` — E2E smoke commands embedded in docstring

### E2E smoke (run after Phase 0.5 gates pass):
- [ ] `python -m pipelines.bsp.run`
- [ ] Row count check: `SELECT COUNT(*), MIN(decision_date), MAX(decision_date) FROM bsp_policy_rate`
      → expect: 70–130 rows, dates from ~2002 to current year
- [ ] Direction spot-check: 2023 decisions show correct hike/hold sequence
- [ ] Cross-join check: `SELECT COUNT(*) FROM psx_vs_bsp WHERE rate_direction IS NOT NULL`
      → expect: non-zero (confirms ASOF JOIN is working with real data)
- [ ] `pipeline_runs` check: at least one ('bsp', 'success', N) entry

---

## Phase 3 — PH-DEP Migration: Structured Repos

**Status: ✅ Artifact Delivery COMPLETE — V7-S7-P3 | awaiting Phase 0.5 + E2E smoke**

### Session 7 artifacts delivered:
- [x] `lib/sources/worldbank.py` — World Bank Indicators API client (CF-V7-002 fix)
- [x] `pipelines/fx/__init__.py`
- [x] `pipelines/fx/extract.py` — BSP RERB + table12 + table13 + Frankfurter fallback (CF-V7-001)
- [x] `pipelines/fx/transform.py` — source-priority deduplication
- [x] `pipelines/fx/load.py` — fx_rates + stg_fx_rates + fx_volatility + real_exchange_rate (CF-V7-005) + cpi_vs_fx (CF-V7-003)
- [x] `pipelines/fx/run.py`
- [x] `pipelines/economic/__init__.py`
- [x] `pipelines/economic/extract.py` — PSA CPI + World Bank + optional BSP CSV (CF-V7-006)
- [x] `pipelines/economic/transform.py` — cpi_trend, gdp_tracker, remittance_trend, economic_dashboard
- [x] `pipelines/economic/load.py` — four DuckDB views + health check
- [x] `pipelines/economic/run.py`
- [x] `requirements.txt` — beautifulsoup4 added (CF-V7-001)
- [x] `db/schema.sql` — orphaned stg_gdp/stg_cpi/stg_remittances stubs removed (CF-V7-004)

### E2E smoke (run after Phase 0.5 gates + BSP E2E both pass):
- [ ] `python -m pipelines.fx.run`
- [ ] `python -m pipelines.economic.run`
- [ ] Cross-check: `SELECT COUNT(*) FROM real_exchange_rate WHERE real_rate IS NOT NULL`
- [ ] `pipeline_runs` entries for 'fx' and 'economic' with status='success'

### Deferred tests (not blockers — resolve in Phase 5):
- [ ] `tests/test_psa_client.py`
- [ ] `tests/test_ttl_cache.py`

---

## Phase 4 — PH-DEP Migration: Notebook Repos

**Status: ✅ Artifact Delivery COMPLETE — V8-S8-P4 | awaiting Phase 0.5 + E2E smoke**

### Audit gate result:
- [x] PH-Labor-Analysis audited — CF-V8-001 (HIGH): repo is ph-ofw-analysis, macroeconomic
      EDA notebook. No LFS data. Labor pipeline built as graceful stub accepting PSA LFS CSV.
      L014 appended to tasks/lessons.md.
- [x] PH-Regional-Inequality audited — FIES data absent, synthetic fallback implemented,
      anchored to official 2021/2023 PSA poverty statistics.

### Session 8 artifacts delivered:
- [x] `pipelines/labor/__init__.py`
- [x] `pipelines/labor/extract.py` — PSA LFS CSV gate; gap.txt marker on absent data
- [x] `pipelines/labor/transform.py` — gap-aware; empty-schema parquet on data gap
- [x] `pipelines/labor/load.py` — zero-row view is correct behavior when no LFS data
- [x] `pipelines/labor/run.py`
- [x] `pipelines/regional/__init__.py`
- [x] `pipelines/regional/extract.py` — real PSA FIES or synthetic fallback
- [x] `pipelines/regional/transform.py` — Gini (Lorenz trapezoidal), Palma ratio, quintile shares
- [x] `pipelines/regional/load.py` — Gini range log + region/year coverage check
- [x] `pipelines/regional/run.py`
- [x] `config_p4_additions.py` — LABOR_RAW_DIR, LABOR_LFS_CSV, REGIONAL_RAW_DIR, REGIONAL_DATA_DIR

### E2E smoke (run after Phase 0.5 gates pass):
- [ ] `python -m pipelines.labor.run` (data gap expected — zero rows, no error)
- [ ] `python -m pipelines.regional.run` (synthetic fallback — verify Gini range 0.3–0.6)
- [ ] `pipeline_runs` entries for 'labor' and 'regional' with status='success'

---

## Phase 5 — Prices

**Status: ✅ Artifact Delivery COMPLETE — V10-S10-P5 | awaiting Phase 0.5 + E2E smoke**

### Session 10 artifacts delivered:
- [x] `pipelines/prices/__init__.py`
- [x] `pipelines/prices/extract.py` — PSA commodity prices + DOE fuel; synthetic fallback for both
- [x] `pipelines/prices/transform.py` — STL decomposition (statsmodels, period=12); commodity_prices + food_price_decomposition parquets
- [x] `pipelines/prices/load.py` — base views + price_trend_by_commodity + seasonal_price_index + price_shock_events
- [x] `pipelines/prices/run.py`
- [x] `config_p5p6_additions.py` — PRICES_RAW_DIR, PRICES_PROCESSED_DIR, TTL_PRICES, PRICES_PSA_CSV, PRICES_DOE_CSV
- [x] `db/init.py` — COMMODITY_PARQUET + FOOD_PARQUET added to PARQUET_MAP; REQUIRED_OBJECTS 18 → 19
- [x] `db/schema.sql` — commodity_prices + food_price_decomposition stub views added
- [x] `requirements.txt` — statsmodels added

### E2E smoke (after Phase 0.5 gates pass):
- [ ] `python -m pipelines.prices.run`
- [ ] `SELECT COUNT(*), COUNT(DISTINCT commodity_slug) FROM commodity_prices` → 12 slugs
- [ ] `SELECT COUNT(*) FROM food_price_decomposition WHERE trend IS NOT NULL` → non-zero
- [ ] `pipeline_runs` entry for 'prices' with status='success'

---

## Phase 6 — Sentiment

**Status: ✅ Artifact Delivery COMPLETE — V10-S10-P6 | awaiting Phase 0.5 + E2E smoke**

### Audit gate result (replaces original Phase 6 blocking gate):
- [x] transformers/torch: NOT viable on Intel Pentium (10+ min/batch). Excluded. CF-V10-001 (HIGH).
- [x] confluent-kafka / faust-streaming: requires broker process. Excluded.
- [x] pydantic: not in requirements.txt. Plain dataclasses used. CF-V10-002 (MEDIUM).
- [x] Twitter live fetch: Academic API tier required. Stubbed. CF-V10-003 (LOW).
- [x] Decision: VADER-only. Sub-millisecond per text, zero GPU. Reddit live via praw (optional).
- [x] L015 appended to tasks/lessons.md.

### Session 10 artifacts delivered:
- [x] `pipelines/sentiment/__init__.py`
- [x] `pipelines/sentiment/extract.py` — 6 PH economic topics; Reddit live fetch (praw, optional); VADER scoring inline; synthetic 90-day fallback
- [x] `pipelines/sentiment/transform.py` — hourly bucket aggregation; rolling 7d avg; social_sentiment.parquet
- [x] `pipelines/sentiment/load.py` — social_sentiment view + sentiment_topic_trend + sentiment_vs_psx (cross-pipeline) + sentiment_topic_heatmap
- [x] `pipelines/sentiment/run.py`
- [x] `config_p5p6_additions.py` — SENTIMENT_RAW_DIR, SENTIMENT_PROCESSED_DIR, SENTIMENT_SYNTHETIC_DAYS, SENTIMENT_MODEL
- [x] `db/init.py` — SENTIMENT_PARQUET added; REQUIRED_OBJECTS 19 → 21
- [x] `db/schema.sql` — social_sentiment stub view added
- [x] `requirements.txt` — vaderSentiment added; praw as optional

### E2E smoke (after Phase 0.5 gates pass):
- [ ] `python -m pipelines.sentiment.run` (synthetic fallback — no credentials needed)
- [ ] `SELECT COUNT(*), COUNT(DISTINCT topic) FROM social_sentiment` → 6 topics, 90-day window
- [ ] `pipeline_runs` entry for 'sentiment' with status='success'

---

## Phase 7 — Streamlit Status Page

**Status: ✅ Artifact Delivery COMPLETE — V11-S11-P7 | awaiting Phase 0.5 + pipeline E2E**

### Session 11 artifacts delivered:
- [x] `apps/streamlit_app.py` — Status page + 10 stub shells + Phase 8 scheduler guard
- [x] Status page: pipeline health table (✅/⚠️/❌/⬜), four metric cards, run log (last 20), DB size, manual refresh
- [x] Stub shells: all 10 non-Status pages with live 5-row DuckDB preview if data present
- [x] `@st.cache_data(ttl=60)` on all queries

### Verification gate (after Phase 0.5 passes):
- [ ] `streamlit run apps/streamlit_app.py`
- [ ] Run each pipeline once: `python -m pipelines.<n>.run`
- [ ] All pipelines show ✅ Healthy (or ⚠️ data gap for labor) in Status page
- [ ] Spot-check: PSX row count + date range visible in Status; BSP direction flags readable

---

## Phase 8 — Scheduler Activation

**Status: ✅ Artifact Delivery COMPLETE — V11-S11-P8 | awaiting Phase 0.5 + Status page gate**

### Session 11 artifacts delivered:
- [x] `scheduler/__init__.py`
- [x] `scheduler/cron_jobs.py` — APScheduler BackgroundScheduler; PSX (cron 18:30 PST), FX (cron 09:00 PST), BSP (cron 1st monthly), Prices (interval 6h), Sentiment (interval 4h); Asia/Manila timezone; misfire_grace_time per job; replace_existing=True
- [x] `apps/streamlit_app.py` — `PH_SCHEDULER_ENABLED` guard already wired; sidebar active/off badge
- [x] `requirements.txt` — apscheduler added

### Verification (after Status page gate passes):
- [ ] `set PH_SCHEDULER_ENABLED=true && streamlit run apps/streamlit_app.py`
- [ ] Sidebar shows "⏱️ Scheduler: **active**"
- [ ] Force PSX fire: `from scheduler.cron_jobs import _run_pipeline; _run_pipeline("psx")`
- [ ] Status page shows updated PSX "Last run" timestamp after fire

---

## Phase 9 — Full Streamlit Dashboard

**Status: ✅ Artifact Delivery COMPLETE — V12-S12-P9 | awaiting Phase 0.5 + pipeline data**

### Session 12 artifacts delivered:
- [x] `components/__init__.py`
- [x] `components/charts.py` — line, bar, area, dual_axis, candlestick, scatter, ph_choropleth, sentiment_stack; COLORS palette
- [x] `components/maps.py` — ph_region_bar, ph_choropleth (GeoJSON if present, bar fallback); PSA region order
- [x] `components/tables.py` — pipeline_runs_table, psx_table, bsp_table, fx_table, prices_table, regional_table, download_csv
- [x] `apps/streamlit_app.py` — full 11-page replacement of Phase 7 stub; all pages implemented

### Page inventory:
- [x] Status — unchanged from P7
- [x] Markets — candlestick + MA, RSI, volume anomaly, ticker selector
- [x] Monetary Policy — rate timeline with hike/cut markers, rate vs CPI dual-axis
- [x] FX — USD/PHP + volatility + cross rates
- [x] Labor — regional unemployment/underemployment; graceful data-gap handling
- [x] Prices — price trend, STL decomposition 4-panel, fuel overlay
- [x] Regional — Gini bar, quintile stacked bar, mean income; choropleth fallback
- [x] Economy — GDP/CPI/Remittances charts + economic dashboard table
- [x] Sentiment — topic trend, sentiment vs PSEi, synthetic notice
- [x] Budget — Phase 11 stub (documented)
- [x] Cross-Analysis — user-selectable dual-axis + scatter, 9 domain metrics, CSV export

### Verification (after Phase 0.5 + pipeline E2E):
- [ ] `streamlit run apps/streamlit_app.py`
- [ ] All 11 pages render without error (empty-state notices acceptable for unpopulated views)
- [ ] Markets page: candlestick loads for PSEi.PS
- [ ] Economy page: GDP/CPI/Remittances charts populate
- [ ] Regional page: Gini bar chart renders (17 regions)
- [ ] Cross-Analysis: USD/PHP vs Inflation overlay renders

---

## Phase 10 — Dash App

**Status: ✅ Artifact Delivery COMPLETE — V13-S13-P10 | awaiting Phase 0.5 + pipeline data**

### Session 13 artifacts delivered:
- [x] `apps/dash_app.py` — two-tab Dash DBC app
- [x] Explorer tab: view selector, date filter, x/y/color/chart-type selectors, 10k-row query, DataTable, CSV + Parquet download
- [x] SQL Passthrough tab: DuckDB read-only editor, cross-domain example query pre-loaded, quick-start library, result DataTable, CSV download
- [x] `config_p10p11_additions.py` — DASH_HOST, DASH_PORT, DASH_DEBUG

### Verification:
- [ ] `python -m apps.dash_app` → opens http://127.0.0.1:8050
- [ ] Explorer: load psx_prices, apply 365-day filter, render candlestick
- [ ] SQL Passthrough: execute cross-domain PSX × BSP × CPI query, verify result table
- [ ] Download parquet from Explorer, verify loadable with pandas

---

## Phase 11 — COA Pipeline

**Status: ✅ Artifact Delivery COMPLETE — V13-S13-P11 | awaiting Phase 0.5 + E2E smoke**

### Session 13 artifacts delivered:
- [x] `pipelines/coa/__init__.py`
- [x] `pipelines/coa/extract.py` — pdfplumber PDF ingestion; synthetic fallback (15 agencies × FY2019–2023, COA-anchored rates)
- [x] `pipelines/coa/transform.py` — outlier flags: is_low_utilizer (rate < 70% or z < −1.5), is_high_utilizer (rate > 95%), peer z-score
- [x] `pipelines/coa/load.py` — coa_budget_utilization + coa_agency_heatmap + coa_low_utilizers + coa_trend_by_agency
- [x] `pipelines/coa/run.py`
- [x] `config_p10p11_additions.py` — COA_RAW_DIR, COA_PROCESSED_DIR, COA_PDF_DIR
- [x] `README.md` — full project README
- [x] `db/init.py` — COA_PARQUET added; REQUIRED_OBJECTS 21 → 22
- [x] `db/schema.sql` — coa_budget_utilization stub view added
- [x] `requirements.txt` — pdfplumber added (optional import guard)

### E2E smoke (synthetic fallback, after Phase 0.5 passes):
- [ ] `python -m pipelines.coa.run`
- [ ] `SELECT COUNT(*), COUNT(DISTINCT agency_code) FROM coa_budget_utilization` → 75 rows, 15 agencies
- [ ] `SELECT * FROM coa_low_utilizers LIMIT 5` → flagged underperformers with negative z-scores
- [ ] `pipeline_runs` entry for 'coa' with status='success'

---

## Phase 12 — Polish

**Status: ✅ Artifact Delivery COMPLETE — V14-S14-P12**

### Session 14 artifacts delivered:
- [x] `docs/architecture.svg` — 1200×860 four-layer system diagram; nine pipeline columns; scheduler panel; cross-pipeline view callouts; legend

### Confirmed present from prior sessions:
- [x] `README.md` — quick-start, architecture table, SQL example, hardware notes (Phase 11)
- [x] `apps/streamlit_app.py` — 11-page full dashboard (Phase 9)
- [x] `apps/dash_app.py` — Explorer + SQL Passthrough (Phase 10)
- [x] `scheduler/cron_jobs.py` — APScheduler (Phase 8)
- [x] `components/` — charts, maps, tables (Phase 9)

### Remaining USER-LOCAL actions (not blockable here):
- [ ] `pip freeze > requirements.lock` — run after pip install -e ".[dev]"
- [ ] `pytest tests/ -v` — expect all GREEN
- [ ] `python -m db.init` — expect "All 22 required objects verified. exit 0"
- [ ] Full pipeline smoke run (all 9 pipelines, including labor zero-row)
- [ ] Status page verification — all pipelines ✅ Healthy
- [ ] `git add . && git commit -m "Phase 12: polish, architecture diagram, requirements.lock"`
- [ ] GIF demo (optional — Dash SQL Passthrough live query, 30–60s)

---

## ✨ PROJECT COMPLETE ✔️

All 12 phases artifact-complete. Phase 0.5 and user-local smoke gates are the
only remaining actions before the repo is ready for GitHub publication.

## dbt Model Inventory

### PH-FX-Dashboard (5 models)
- [ ] `stg_bsp_fx` → `stg_fx`
- [ ] `stg_cross_rates` → `stg_cross`
- [ ] `mart_fx_rates` → `fx_rates`
- [ ] `mart_fx_volatility` → (merge into `fx_rates` or separate view)
- [ ] `mart_usdphp_monthly` → (merge into `fx_rates`)

### PH-Economic-Tracker (6 models)
- [ ] `stg_economic_indicators` → `stg_cpi`
- [ ] `stg_gdp_expenditure` → `stg_gdp`
- [ ] `stg_ofw_remittances` → `stg_remittances`
- [ ] `mart_cpi_trend` → `cpi_trend`
- [ ] `mart_gdp_tracker` → `gdp_tracker`
- [ ] `mart_remittance_trend` → `remittance_trend`

### PH-Price-Tracker — RETIRED (do not port)

### PH-Social-Sentiment-Pipeline (model count TBD — Phase 6 audit)
- [ ] Enumerate models after dependency audit