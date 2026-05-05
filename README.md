# PH Economic Intelligence Dashboard

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![DuckDB](https://img.shields.io/badge/DuckDB-0.10+-FFC107?style=for-the-badge&logo=duckdb&logoColor=black)](https://duckdb.org/)
[![Next.js](https://img.shields.io/badge/Next.js-15-000000?style=for-the-badge&logo=next.js&logoColor=white)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-latest-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.35+-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white)](https://streamlit.io/)
[![Status](https://img.shields.io/badge/Status-Stable-4CAF50?style=for-the-badge)](https://github.com/raldisk/ph-dashboard)
[![Version](https://img.shields.io/badge/Version-v1.0.0-blue?style=for-the-badge)](https://github.com/raldisk/ph-dashboard)
[![License](https://img.shields.io/badge/License-See_ATTRIBUTION.md-green?style=for-the-badge)](ATTRIBUTION.md)
[![CI](https://img.shields.io/github/actions/workflow/status/raldisk/ph-dashboard/ci.yml?branch=master&label=CI&style=for-the-badge&logo=github)](https://github.com/raldisk/ph-dashboard/actions)

> **Philippine Economic Intelligence Dashboard** — a locally-hosted multi-domain data platform integrating ten Philippine economic datasets into a unified DuckDB-backed analytical dashboard.

Data flows from ten heterogeneous sources through a shared ETL contract into a DuckDB analytical warehouse, served by FastAPI and visualised across four frontend clients.

---

## Table of Contents

- [Ecosystem](#ecosystem)
- [Architecture](#architecture)
- [What It Does](#what-it-does)
- [Quick Start](#quick-start)
- [Before You Deploy](#before-you-deploy)
- [Service Endpoints](#service-endpoints)
- [Presentation Clients](#presentation-clients)
- [Running Pipelines](#running-pipelines)
- [API Reference](#api-reference)
- [Scheduled Pipelines](#scheduled-pipelines)
- [DuckDB Views](#duckdb-views)
- [Data Gaps and Fallbacks](#data-gaps-and-fallbacks)
- [Design Decisions](#design-decisions)
- [Repository Structure](#repository-structure)
- [Tech Stack](#tech-stack)

---

## Ecosystem

This dashboard is the **downstream analytics layer** of a two-tier Philippine economic intelligence platform.

**[ph-macro-lakehouse](https://github.com/raldisk/ph-macro-lakehouse)** is the upstream producer — it runs a production-grade Bronze→Silver→Gold medallion pipeline for PSA CPI and BSP FX data with YAML quality contracts, SHA-256 dedup, and quarantine writes. When the lakehouse is running, this dashboard's `pipelines/bsp/` and `pipelines/fx/` are replaced by a lakehouse adapter that consumes `GET /gold/{dataset}/data` directly. Legacy pipelines remain as automatic fallback if the lakehouse is unavailable.

---

## Architecture

![PH-Dashboard Architecture](img/architecture.svg)

Five layers: external data sources → ETL pipelines → DuckDB local storage → orchestration + FastAPI serving → four presentation clients. The teal lane tracks the geospatial pipeline end-to-end. Streamlit and Dash read DuckDB directly (no API hop). Next.js and ph-hazard-map consume the FastAPI `/api/v1` layer.

---

## What It Does

| Domain | Source | Pipeline | Tables |
|--------|--------|----------|--------|
| PSX Equity Prices | yfinance | `pipelines/psx/` | `psx_prices` |
| BSP Monetary Policy | BSP bulletins (HTML) | `pipelines/bsp/` | `bsp_policy_rate` |
| FX Rates | BSP reference rates | `pipelines/fx/` | `fx_rates`, `stg_fx_rates`, `fx_volatility` |
| Economic Indicators | PSA OpenSTAT + World Bank | `pipelines/economic/` | `cpi_trend`, `gdp_tracker`, `remittance_trend`, `economic_dashboard` |
| Labor Market | PSA LFS (manual CSV) | `pipelines/labor/` | `labor_market` |
| Regional Inequality | PSA FIES (synthetic fallback) | `pipelines/regional/` | `regional_inequality` |
| Commodity Prices | PSA Price Situationer + DOE | `pipelines/prices/` | `commodity_prices`, `food_price_decomposition` |
| Social Sentiment | Reddit (VADER-scored) | `pipelines/sentiment/` | `social_sentiment` |
| COA Budget | COA Annual Audit Reports (PDF) | `pipelines/coa/` | `coa_budget_utilization` |
| Geodata / Hazard | GeoRisk PH ArcGIS | `pipelines/geodata/` | `regional_map`, `hazard_overlap_by_province` |

Every pipeline exposes a uniform four-function contract: `extract()` → `transform()` → `load()` → `run()`.

---

## Quick Start

**Prerequisites:** Python 3.11+, Node 20+ (for Next.js clients only).

```bash
# 1. Install
pip install -e ".[dev]"

# 2. Initialize database
python -m db.init

# 3. Run pipelines
python -m pipelines.psx.run
python -m pipelines.bsp.run
python -m pipelines.fx.run
python -m pipelines.economic.run
python -m pipelines.regional.run   # synthetic fallback — no data needed
python -m pipelines.prices.run     # synthetic fallback — no data needed
python -m pipelines.sentiment.run  # synthetic fallback — no credentials needed
python -m pipelines.coa.run        # synthetic fallback — no PDFs needed

# 4. Launch Streamlit (analyst view)
streamlit run apps/streamlit_app.py

# 5. Launch Dash (power-user / SQL explorer)
python -m apps.dash_app

# 6. Launch FastAPI (required for Next.js and hazard map)
uvicorn api.main:app --reload --port 8000

# 7. Launch Next.js dashboard (optional)
cd dashboard && npm ci && npm run dev          # http://localhost:3000

# 8. Launch hazard map (optional)
cd ph-hazard-map && npm ci && npm run dev     # http://localhost:3001
```

---

## Before You Deploy

> These are not optional — address all four before any public-facing deployment.

- **No authentication layer** — all API endpoints are open. Add auth before exposing to a network.
- **No rate limiting** — the FastAPI layer has no throttling. Add before any public exposure.
- **Seed GeoJSON not committed** — run `git add -f` on seed files before pushing or the geodata pipeline cold-starts empty.
- **Use `.env` not `.env.example`** — the compose file expects real env values, not the example template.

---

## Service Endpoints

| Service | URL | Notes |
|---------|-----|-------|
| Streamlit | http://localhost:8501 | Analyst / narrative view |
| Dash | http://localhost:8050 | Power-user explorer + SQL passthrough |
| Next.js Dashboard | http://localhost:3000 | IBM Carbon UI, KPI cards, SQL editor |
| ph-hazard-map | http://localhost:3001 | MapLibre GL hazard + vulnerability layers |
| FastAPI + Swagger | http://localhost:8000/docs | Required for Next.js and hazard map |

---

## Presentation Clients

| Client | Port | Data path | Primary use |
|--------|------|-----------|-------------|
| Streamlit | 8501 | DuckDB direct | Analyst / narrative view |
| Dash | 8050 | DuckDB direct | Power-user explorer + SQL passthrough |
| Next.js Dashboard | 3000 | FastAPI `/api/v1` | IBM Carbon UI, KPI cards, SQL editor |
| ph-hazard-map | 3001 | FastAPI `/api/v1/data?format=geojson` | MapLibre GL hazard + vulnerability layers |

---

## Running Pipelines

### On-demand

```bash
python -m pipelines.psx.run
python -m pipelines.bsp.run
python -m pipelines.fx.run
python -m pipelines.economic.run
python -m pipelines.labor.run
python -m pipelines.regional.run
python -m pipelines.prices.run
python -m pipelines.sentiment.run
python -m pipelines.coa.run
python -m pipelines.geodata.run
```

### Scheduled (APScheduler)

Set `PH_SCHEDULER_ENABLED=true` before launching Streamlit to activate the background scheduler (Philippine Standard Time, UTC+8):

```bash
PH_SCHEDULER_ENABLED=true streamlit run apps/streamlit_app.py
```

---

## API Reference

Base URL: `http://localhost:8000/api/v1`

All endpoints are read-only. The `X-PH-Synthetic-Data` response header indicates whether the underlying data is real or synthetic fallback.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/data?view=<name>` | View data — 1h TTL cache — `&format=geojson` for map clients |
| `GET` | `/views` | List all registered DuckDB views |
| `GET` | `/query` | Arbitrary read-only DuckDB SQL |
| `GET` | `/kpi` | Aggregated KPI summary payload |
| `GET` | `/health` | Liveness — always 200 |
| `GET` | `/health/ready` | Readiness — DuckDB + pipeline_runs check · 503 on fail |

**SQL passthrough example** — cross-domain query against all pipeline views:

```sql
SELECT
    DATE_TRUNC('month', p.date)::DATE  AS month,
    AVG(p.close)                       AS avg_psei,
    b.overnight_rp                     AS bsp_rate,
    c.inflation_pct
FROM psx_prices p
LEFT JOIN bsp_policy_rate b
    ON DATE_TRUNC('month', p.date) = DATE_TRUNC('month', b.decision_date)
LEFT JOIN cpi_trend c
    ON DATE_TRUNC('month', p.date) = c.period_date
WHERE p.ticker = 'PSEi.PS'
GROUP BY 1, b.overnight_rp, c.inflation_pct
ORDER BY 1;
```

---

## Scheduled Pipelines

| Pipeline | Trigger | Schedule (PST) |
|----------|---------|----------------|
| PSX | daily cron | 18:30 |
| FX | daily cron | 09:00 |
| BSP | monthly cron | 1st of month, 08:00 |
| Prices | interval | every 6h |
| Sentiment | interval | every 4h |
| Geodata | monthly cron | 1st of month, 03:00 |

Static pipelines (run manually per release cycle): `economic`, `labor`, `regional`, `coa`.

---

## DuckDB Views

```
psx_prices               bsp_policy_rates         stg_fx_rates
cpi_trend                lfs_labor_force          fies_regional
commodity_prices         food_price_decomp        social_sentiment
coa_budget_util          regional_map             road_quality_by_province
provincial_vulnerability_index                    hazard_overlap_by_province
psx_vs_bsp               real_exchange_rate       sentiment_vs_psx
```

Cross-pipeline joins use DuckDB `ASOF JOIN` on date columns. TTL cache at `lib/sources/ttl_cache.py` guards re-fetch with `threading.Lock` + mtime-based invalidation.

---

## Data Gaps and Fallbacks

| Pipeline | Fallback | To activate real data |
|----------|----------|-----------------------|
| Labor | Empty schema (zero rows) | Download PSA LFS CSV, set `cfg.LABOR_LFS_CSV` |
| Regional | Synthetic FIES (PSA-anchored) | Download FIES CSVs, set `cfg.REGIONAL_DATA_DIR` |
| Prices | Synthetic PSA/DOE (anchored) | Download bulletins, set `cfg.PRICES_PSA_CSV` / `cfg.PRICES_DOE_CSV` |
| Sentiment | Synthetic 90-day trailing | Set `REDDIT_CLIENT_ID` + credentials in `.env` |
| COA | Synthetic FY2019–2023 | Download PDFs, set `cfg.COA_PDF_DIR` |
| Geodata | Seed GeoJSON cold-start render | `git add -f` seed files before push |

All pipelines complete without error in fallback mode. The Status page (`📊 Status`) shows actual row count and source per domain.

---

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| DuckDB over PostgreSQL | No server process — single-file analytical store, zero ops overhead for local deployment |
| APScheduler over Celery/Prefect | Embedded background thread — no separate worker process or broker required |
| VADER over transformer NLP | VADER runs in milliseconds per document; transformer models (BERT, XLM-RoBERTa) require GPU or >10 min/batch on CPU-only hardware |
| Synthetic fallbacks on all pipelines | Zero-error execution regardless of source availability — system always starts, always renders |
| Four frontend clients | Different audiences: Streamlit for analysts, Dash for SQL power users, Next.js for UI-first consumers, MapLibre for geospatial |

---

## Repository Structure

```
PH-Dashboard/
├── pipelines/          # Ten ETL pipeline modules (uniform extract→transform→load→run)
│   ├── psx/            # PSX OHLCV + RSI + MA signals
│   ├── bsp/            # Monetary policy rate decisions
│   ├── fx/             # Exchange rates + volatility
│   ├── economic/       # GDP, CPI, OFW remittances
│   ├── labor/          # LFS unemployment (user-supplied CSV)
│   ├── regional/       # FIES Gini + income quintiles
│   ├── prices/         # Commodity retail + STL decomposition
│   ├── sentiment/      # VADER-scored Reddit sentiment
│   ├── coa/            # COA audit report PDF ingestion
│   └── geodata/        # GeoRisk hazard layers + province boundaries
├── api/
│   ├── main.py         # FastAPI app, CORS, lifespan
│   ├── routes/         # data.py · health.py
│   ├── schemas/        # Pydantic request/response models
│   └── services/       # query_service.py (DuckDB read + TTL cache)
├── lib/
│   └── sources/        # Shared HTTP clients (BSP, PSA, World Bank) + ttl_cache.py
├── db/
│   ├── schema.sql          # DuckDB DDL (22 REQUIRED_OBJECTS)
│   ├── schema_geodata.sql  # Geodata DDL
│   ├── seed_region_crosswalk.sql  # 17 PH regions · PSGC codes
│   └── init.py             # Idempotent bootstrap + object verification
├── apps/
│   ├── streamlit_app.py    # 11-page narrative dashboard
│   └── dash_app.py         # Explorer + SQL passthrough
├── components/         # Shared Plotly factories, table configs, map helpers
├── scheduler/
│   └── cron_jobs.py    # APScheduler job registry (background thread)
├── ph-hazard-map/      # Next.js 15 + MapLibre GL (port 3001)
├── img/
│   └── architecture.svg
├── data/
│   ├── raw/            # Unprocessed source files (gitignored)
│   ├── processed/      # Parquet files (gitignored)
│   └── cache/          # TTL-managed fetch cache (gitignored)
├── .github/workflows/ci.yml
├── docker-compose.yml
└── config.py           # Paths, TTLs, pipeline constants
```

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Analytical store | DuckDB 0.10+ |
| ETL | Python 3.11 · pandas · httpx · BeautifulSoup4 · pdfplumber |
| Orchestration | APScheduler (embedded) |
| API | FastAPI · uvicorn · Pydantic |
| Analyst UI | Streamlit 1.35+ |
| Explorer UI | Dash + Plotly |
| Production UI | Next.js 15 · TypeScript · IBM Carbon |
| Geospatial | MapLibre GL · geopandas · shapely |
| NLP | VADER sentiment |
| Statistical | statsmodels (STL decomposition) |
| CI | GitHub Actions |

---

## License

See [ATTRIBUTION.md](ATTRIBUTION.md) for data source attributions and licensing notes.
