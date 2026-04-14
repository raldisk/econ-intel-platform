# PH Economic Intelligence Dashboard

A locally-hosted multi-domain data platform integrating nine Philippine economic
datasets into a unified DuckDB-backed analytical dashboard. Built for finance-sector
portfolio positioning — the architecture demonstrates the complete data engineering
stack in a single repository.

![Status](https://img.shields.io/badge/status-active-brightgreen)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![DuckDB](https://img.shields.io/badge/DuckDB-0.10%2B-yellow)
![Streamlit](https://img.shields.io/badge/Streamlit-1.35%2B-red)

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

# 4. Launch dashboard
streamlit run apps/streamlit_app.py

# 5. Launch explorer (optional)
python -m apps.dash_app
```

---

## Architecture

```
PH-Dashboard/
├── pipelines/          # Nine E/T/L pipeline modules (uniform interface)
│   ├── psx/            # PSX OHLCV + RSI + MA signals
│   ├── bsp/            # Monetary policy rate decisions
│   ├── fx/             # Exchange rates + volatility
│   ├── economic/       # GDP, CPI, OFW remittances
│   ├── labor/          # LFS unemployment (user-supplied CSV)
│   ├── regional/       # FIES Gini + income quintiles
│   ├── prices/         # Commodity retail + STL decomposition
│   ├── sentiment/      # VADER-scored Reddit sentiment
│   └── coa/            # COA audit report PDF ingestion
├── lib/
│   └── sources/        # Shared HTTP clients (BSP, PSA, World Bank)
├── db/
│   ├── schema.sql      # DuckDB DDL (placeholder views, sequence)
│   └── init.py         # Bootstrap + REQUIRED_OBJECTS verification
├── apps/
│   ├── streamlit_app.py  # 11-page narrative dashboard
│   └── dash_app.py       # Exploratory view + SQL passthrough
├── components/         # Shared Plotly factories, table configs, map helpers
├── scheduler/
│   └── cron_jobs.py    # APScheduler job registry (background thread)
├── data/
│   ├── raw/            # Unprocessed source files (gitignored)
│   ├── processed/      # Parquet files (gitignored)
│   └── cache/          # TTL-managed fetch cache (gitignored)
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

## Scheduled pipelines

Set `PH_SCHEDULER_ENABLED=true` before launching Streamlit to activate
the APScheduler background thread (Philippine Standard Time, UTC+8):

| Pipeline | Trigger | Time |
|---|---|---|
| PSX | daily cron | 18:30 PST |
| FX | daily cron | 09:00 PST |
| BSP | monthly cron | 1st, 08:00 PST |
| Prices | interval | every 6 h |
| Sentiment | interval | every 4 h |

Static pipelines (run manually per release cycle):
`economic`, `labor`, `regional`, `coa`

---

## SQL passthrough panel

The Dash explorer at `http://127.0.0.1:8050` includes a live SQL editor
connected to the local DuckDB. Cross-domain queries run against all nine
pipeline views simultaneously:

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
| Sentiment | Synthetic 90-day trailing | Set `REDDIT_CLIENT_ID` + credentials |
| COA | Synthetic FY2019–2023 | Download PDFs, set `cfg.COA_PDF_DIR` |

All pipelines are designed to complete without error in fallback mode.
The Status page (`📊 Status`) reflects the actual row count and source.

---

## Hardware notes

Built for **Intel Pentium CPU, Windows 10 native** (no Docker, no WSL):

- DuckDB replaces PostgreSQL — no server process required
- APScheduler runs as a background thread inside Streamlit — no separate worker
- VADER replaces transformer-based NLP (BERT/XLM-RoBERTa excluded: >10 min/batch on Pentium)
- H.264-compatible where applicable; no GPU dependencies anywhere

---

## Key dependencies

```
duckdb          pandas          pyarrow
streamlit       dash            dash-bootstrap-components
plotly          apscheduler
httpx           beautifulsoup4  pdfplumber
vaderSentiment  statsmodels     yfinance
structlog
```

See `requirements.txt` for pinned versions.
See `requirements.lock` for the full resolved dependency tree.
