from __future__ import annotations

import logging
import logging.handlers
import time
from contextlib import asynccontextmanager
from pathlib import Path

import duckdb
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

import config as cfg
from api.routes.health import router as health_router
from api.routes.data import router as data_router
from api.routes.views_meta import router as views_meta_router
from api.routes.status import router as status_router
from db.init import REQUIRED_OBJECTS

# ---------------------------------------------------------------------------
# Structured rotating log — api/logs/requests.log, 7 days retention
# ---------------------------------------------------------------------------
_LOG_DIR = Path(__file__).parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.TimedRotatingFileHandler(
            _LOG_DIR / "requests.log",
            when="midnight",
            backupCount=7,
            encoding="utf-8",
        ),
    ],
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan — validate-only startup guard.
#
# This hook VALIDATES the database; it does NOT create or migrate it.
# Initialization is a deployment-time step: run `python -m db.init` (or
# `make init`) before starting the server.
#
# Design rationale:
#   - Calling init_db() here would open a read-write DuckDB connection inside
#     each worker's lifespan. Under --workers N, N-1 workers crash immediately
#     with "database is locked" because DuckDB permits only one read-write
#     connection per file. Validate-only uses read_only=True, which DuckDB
#     allows concurrently across all workers.
#   - Failing fast here prevents the server from accepting requests against a
#     missing or schema-incomplete database, which would produce misleading
#     500s rather than a clear operational error.
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── 1. File existence check ──────────────────────────────────────────────
    if not cfg.DB_PATH.exists():
        raise RuntimeError(
            f"Database not found at {cfg.DB_PATH}.\n"
            "Run `python -m db.init` (or `make init`) before starting the server."
        )

    # ── 2. Schema completeness check (read-only — safe under N workers) ──────
    try:
        con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
        registered: set[str] = {
            row[0].lower()
            for row in con.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }
        con.close()
    except Exception as exc:
        raise RuntimeError(
            f"Database at {cfg.DB_PATH} could not be opened for validation: {exc}\n"
            "Re-run `python -m db.init` to repair."
        ) from exc

    missing = {obj for obj in REQUIRED_OBJECTS if obj not in registered}
    if missing:
        raise RuntimeError(
            f"Schema incomplete — {len(missing)} missing object(s): {sorted(missing)}\n"
            "Re-run `python -m db.init` to repair."
        )

    logger.info(
        "DB validated at %s — %d/%d required objects confirmed.",
        cfg.DB_PATH,
        len(REQUIRED_OBJECTS),
        len(REQUIRED_OBJECTS),
    )
    yield
    # No teardown required — DuckDB connections are closed per-request.


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="PH-Dashboard API",
    description="Philippine economic intelligence dashboard — local OLAP API.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    logger.info(
        "%s %s %dms HTTP/%s",
        request.method,
        request.url.path + (f"?{request.url.query}" if request.url.query else ""),
        elapsed_ms,
        response.status_code,
    )
    return response


# ---------------------------------------------------------------------------
# Routers — all mounted at root level (no /api/v1 prefix).
# lib/api.ts calls /data, /kpi, /views, /query, /views/meta, /status.
# The not-working version deliberately unified the contract: all routes
# unprefixed, consistent with the new /views/meta and /status endpoints.
# ---------------------------------------------------------------------------
app.include_router(health_router)
app.include_router(data_router)
app.include_router(views_meta_router)
app.include_router(status_router)


@app.get("/")
def root():
    return {"message": "PH Dashboard API running", "docs": "/docs"}
