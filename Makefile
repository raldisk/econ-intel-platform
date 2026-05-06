# PH-Dashboard — operational shortcuts
#
# Dependency order:
#   1. init         — bootstrap DuckDB schema (run once, or after wiping the DB)
#   2. pipelines    — run all ETL pipelines to populate parquets and views
#   3. api          — start FastAPI (reads DuckDB read-only)
#   4. scheduler    — start standalone scheduler (writes DuckDB via pipelines)
#   5. dev          — start Next.js frontend (calls the API)
#   6. streamlit    — start Streamlit (reads DuckDB directly)
#
# The scheduler and api are independent processes — start them in separate
# terminal sessions.  The scheduler MUST NOT be started before init completes.

.PHONY: init pipelines api scheduler dev streamlit typecheck clean help

help:
	@echo "PH-Dashboard process targets:"
	@echo "  make init        — bootstrap DuckDB schema"
	@echo "  make pipelines   — run all ETL pipelines"
	@echo "  make api         — start FastAPI on :8000"
	@echo "  make scheduler   — start standalone APScheduler process"
	@echo "  make dev         — start Next.js on :3000"
	@echo "  make streamlit   — start Streamlit on :8501"
	@echo "  make typecheck   — run tsc --noEmit (requires Node)"
	@echo "  make clean       — remove __pycache__, .next, logs"

init:
	python -m db.init

pipelines:
	python -m pipelines.psx.run
	python -m pipelines.bsp.run
	python -m pipelines.fx.run
	python -m pipelines.economic.run
	python -m pipelines.labor.run
	python -m pipelines.regional.run
	python -m pipelines.prices.run
	python -m pipelines.sentiment.run
	python -m pipelines.coa.run

api:
	uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload

scheduler:
	python -m scheduler.main

dev:
	npm run dev

streamlit:
	streamlit run apps/streamlit_app.py

typecheck:
	npx tsc --noEmit

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .next api/logs scheduler/logs
