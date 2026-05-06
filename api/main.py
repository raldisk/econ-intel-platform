from __future__ import annotations

import logging
import logging.handlers
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from api.routes.health import router as health_router
from api.routes.data import router as data_router
from api.routes.views_meta import router as views_meta_router
from api.routes.status import router as status_router

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
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="PH-Dashboard API",
    description="Philippine economic intelligence dashboard — local OLAP API.",
    version="1.0.0",
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


app.include_router(health_router)
app.include_router(data_router)
app.include_router(views_meta_router)
app.include_router(status_router)


@app.get("/")
def root():
    return {"message": "PH Dashboard API running", "docs": "/docs"}
