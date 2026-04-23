# PH Economic Intelligence Dashboard

A locally-hosted multi-domain data platform integrating nine Philippine economic
datasets into a unified DuckDB-backed analytical dashboard. Built for finance-sector
portfolio positioning — the architecture demonstrates the complete data engineering
stack in a single repository.

![Status](https://img.shields.io/badge/status-RC-brightgreen)
![Version](https://img.shields.io/badge/version-V15--S15--FINAL-blue)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![DuckDB](https://img.shields.io/badge/DuckDB-0.10%2B-yellow)
![Streamlit](https://img.shields.io/badge/Streamlit-1.35%2B-red)
![Next.js](https://img.shields.io/badge/Next.js-15-black)

---

## Architecture

![PH-Dashboard Architecture](img/architecture.svg)

Five layers: external data sources → ETL pipelines → DuckDB local storage →
orchestration + FastAPI serving → four presentation clients. The teal lane tracks
the geospatial pipeline end-to-end; Streamlit and Dash read DuckDB directly (no API
hop); Next.js and ph-hazard-map consume the FastAPI `/api/v1` layer.

> **Pre-deploy checklist (⚠):** add auth layer · add rate limiting ·
> `git add -f` seed GeoJSON · use `.env` not `.env.example` in compose.

---

## What it does

| Domain | Source | Pipeline | Tables |
|---|---|---|---|
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

---

## Quick start

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

# 5. Launch Dash explorer (optional — power-user / SQL)
python -m apps.dash_app

# 6. Launch FastAPI (required for Next.js and hazard map)
uvicorn api.main:app --reload --port 8000

# 7. Launch Next.js dashboard (optional)
cd dashboard && npm ci && npm run dev          # http://localhost:3000

# 8. Launch hazard map (optional)
cd ph-hazard-map && npm ci && npm run dev     # http://localhost:3001
```

---

## Presentation clients

| Client | Port | Data path | Primary use |
|---|---|---|---|
| Streamlit | 8501 | DuckDB direct | Analyst / narrative view |
| Dash | 8050 | DuckDB direct | Power-user explorer + SQL passthrough |
| Next.js Dashboard | 3000 | FastAPI `/api/v1` | IBM Carbon UI, KPI cards, SQL editor |
| ph-hazard-map | 3001 | FastAPI `/api/v1/data?format=geojson` | MapLibre GL hazard + vulnerability layers |

---

## Repository structure

```
PH-Dashboard/
├── pipelines/          # Ten E/T/L pipeline modules (uniform interface)
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
│   └── dash_app.py         # Explorer + SQL passthrough (Tab 1 · Tab 2)
├── components/         # Shared Plotly factories, table configs, map helpers
├── scheduler/
│   └── cron_jobs.py    # APScheduler job registry (background thread)
├── ph-hazard-map/      # Next.js 15 + MapLibre GL (port 3001)
├── img/
│   └── architecture.svg   # System architecture diagram
├── data/
│   ├── raw/            # Unprocessed source files (gitignored)
│   ├── processed/      # Parquet files (gitignored)
│   └── cache/          # TTL-managed fetch cache (gitignored)
├── .github/workflows/ci.yml  # Lint · pytest · db smoke · Next.js build
├── docker-compose.yml
└── config.py           # Paths, TTLs, pipeline constants
```

Every pipeline exposes the same four-function contract:

```python
def extract() -> None: ...   # writes to data/raw/
def transform() -> None: ... # writes parquet to data/processed/
def load() -> None: ...      # registers DuckDB view
def run() -> None:
    extract(); transform(); load()
```

---

## DuckDB views (17)

```
psx_prices             bsp_policy_rates       stg_fx_rates
cpi_trend              lfs_labor_force        fies_regional
commodity_prices       food_price_decomp      social_sentiment
coa_budget_util        regional_map           road_quality_by_province
provincial_vulnerability_index                hazard_overlap_by_province
psx_vs_bsp             real_exchange_rate     sentiment_vs_psx
```

Cross-pipeline joins use DuckDB `ASOF JOIN` on date columns. TTL cache at
`lib/sources/ttl_cache.py` guards re-fetch with `threading.Lock` + mtime-based
invalidation.

---

## Scheduled pipelines

Set `PH_SCHEDULER_ENABLED=true` before launching Streamlit to activate
the APScheduler background thread (Philippine Standard Time, UTC+8):

| Pipeline | Trigger | Schedule |
|---|---|---|
| PSX | daily cron | 18:30 PST |
| FX | daily cron | 09:00 PST |
| BSP | monthly cron | 1st of month, 08:00 PST |
| Prices | interval | every 6 h |
| Sentiment | interval | every 4 h |
| Geodata | monthly cron | 1st of month, 03:00 PST |

Static pipelines (run manually per release cycle):
`economic`, `labor`, `regional`, `coa`

---

## FastAPI endpoints

Base URL: `http://localhost:8000/api/v1`

| Method | Path | Description |
|---|---|---|
| GET | `/data?view=<name>&format=geojson` | View data · 1h TTL cache · GeoJSON mode for map clients |
| GET | `/views` | List all registered DuckDB views |
| GET | `/query` | Arbitrary read-only DuckDB SQL |
| GET | `/kpi` | Aggregated KPI summary payload |
| GET | `/health` | Liveness — always 200 |
| GET | `/health/ready` | Readiness — DuckDB + pipeline_runs check · 503 on fail |

All responses carry `X-PH-Synthetic-Data` header indicating whether the
underlying data is real or synthetic fallback.

---

## SQL passthrough panel

The Dash explorer at `http://127.0.0.1:8050` (Tab 2) includes a live SQL editor
connected to the local DuckDB. Cross-domain queries run against all pipeline
views simultaneously:

```sql
-- PSX close vs BSP rate vs CPI — monthly aligned
SELECT
    DATE_TRUNC('month', p.date)::DATE  AS month,
    AVG(p.close)                       AS avg_psei,
    b.overnight_rp                     AS bsp_rate,
    c.inflation_pct
FROM psx_prices p
LEFT JOIN bsp_policy_rate b
    ON DATE_TRUNC('month', p.date) =
       DATE_TRUNC('month', b.decision_date)
LEFT JOIN cpi_trend c
    ON DATE_TRUNC('month', p.date) = c.period_date
WHERE p.ticker = 'PSEi.PS'
GROUP BY 1, b.overnight_rp, c.inflation_pct
ORDER BY 1;
```

---

## Data gaps and fallbacks

| Pipeline | Fallback | To activate real data |
|---|---|---|
| Labor | Empty schema (zero rows) | Download PSA LFS CSV, set `cfg.LABOR_LFS_CSV` |
| Regional | Synthetic FIES (PSA-anchored) | Download FIES CSVs, set `cfg.REGIONAL_DATA_DIR` |
| Prices | Synthetic PSA/DOE (anchored) | Download bulletins, set `cfg.PRICES_PSA_CSV` / `cfg.PRICES_DOE_CSV` |
| Sentiment | Synthetic 90-day trailing | Set `REDDIT_CLIENT_ID` + credentials in `.env` |
| COA | Synthetic FY2019–2023 | Download PDFs, set `cfg.COA_PDF_DIR` |
| Geodata | Seed GeoJSON cold-start render | `git add -f` seed files before push |

All pipelines complete without error in fallback mode. The Status page
(`📊 Status`) reflects actual row count and source for each domain.

---

## Hardware notes

Built for **Intel Pentium CPU, Windows 10 native** (no Docker, no WSL required
for development):

- DuckDB replaces PostgreSQL — no server process required
- APScheduler runs as a background thread inside Streamlit — no separate worker
- VADER replaces transformer-based NLP (BERT/XLM-RoBERTa excluded: >10 min/batch on Pentium)
- H.264-compatible output where applicable; no GPU dependencies anywhere

---

## Key dependencies

```
duckdb          pandas          pyarrow
streamlit       dash            dash-bootstrap-components
plotly          apscheduler
fastapi         uvicorn         httpx
beautifulsoup4  pdfplumber
vaderSentiment  statsmodels     yfinance
structlog       geopandas       shapely
```

See `requirements.txt` for pinned versions.

---

## License

See `ATTRIBUTION.md` for data source attributions and licensing notes.
