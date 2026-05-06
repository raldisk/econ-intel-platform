"""
scheduler/cron_jobs.py — APScheduler job registry.

Run as a standalone process via scheduler/main.py:

    python -m scheduler.main

The scheduler is NOT embedded in any frontend process.  It runs independently
so that pipeline execution survives Streamlit restarts and hot-reloads.

Job schedule (Philippine Standard Time = UTC+8):

  Pipeline     Trigger    Time (PST)       Rationale
  ──────────   ─────────  ───────────────  ─────────────────────────────────────
  psx          cron       18:30 daily      PSE closes 15:30; delay allows yfinance cache
  fx           cron       09:00 daily      BSP publishes morning reference rates
  bsp          cron       1st of month     Policy decisions are monthly
  prices       interval   every 6 h        DA/NFA bulletins update intra-day
  sentiment    interval   every 4 h        Social media cadence; Reddit API rate limits

Static pipelines (not scheduled — CLI only):
  economic, labor, regional, coa
  Trigger manually: python -m pipelines.<name>.run

All jobs write to pipeline_runs on completion (success or error).
The Streamlit Status page queries pipeline_runs to reflect real-time state.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# PATCH FINDING-002: module-level scheduler instance so that .running reflects
# the true state of the scheduler across all call sites.  A fresh instance
# constructed inside start_scheduler() always has .running == False, making
# the guard a no-op and allowing duplicate job registration when the function
# is called from outside the streamlit_app.py context.
_scheduler = None

# APScheduler timezone handling:
# Use 'Asia/Manila' for Philippine Standard Time (UTC+8, no DST).
# Requires pytz or zoneinfo — APScheduler accepts both.
_TZ = "Asia/Manila"

# Write lock — DuckDB allows only one writer at a time.  Two scheduler jobs
# firing simultaneously (e.g. prices at 6h + sentiment at 4h overlapping)
# serialize here at the Python layer for a clean error surface.
import threading
_write_lock = threading.Lock()


def _run_pipeline(name: str) -> None:
    """
    Import and execute a pipeline's run() function inside a try/except.
    Acquires _write_lock so overlapping cron jobs serialize cleanly.
    pipeline_runs logging is handled inside each load.py.
    """
    logger.info("Scheduler: acquiring write lock for pipeline '%s'.", name)
    with _write_lock:
        try:
            import importlib
            module = importlib.import_module(f"pipelines.{name}.run")
            module.run()
            logger.info("Scheduler: pipeline '%s' completed successfully.", name)
        except Exception as exc:
            logger.error(
                "Scheduler: pipeline '%s' failed: %s",
                name, exc, exc_info=True,
            )


def start_scheduler() -> None:
    """
    Configure and start the APScheduler BackgroundScheduler.

    Called once at app startup when PH_SCHEDULER_ENABLED=true.
    Safe to call multiple times — subsequent calls are no-ops because
    the module-level _scheduler instance is checked for .running state.

    PATCH FINDING-002: guard now checks .running on the persistent module-level
    _scheduler instance rather than on a freshly constructed one (which is never
    in running state, making the old guard a no-op).
    """
    global _scheduler

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger
    except ImportError as exc:
        logger.error(
            "APScheduler not installed. pip install apscheduler. "
            "Scheduler NOT started: %s", exc,
        )
        return

    # Guard on persistent instance — blocks duplicate job registration from
    # any call site, not only the streamlit_app.py path.
    if _scheduler is not None and _scheduler.running:
        logger.info("Scheduler already running — skipping start.")
        return

    _scheduler = BackgroundScheduler(timezone=_TZ)
    scheduler = _scheduler

    # ── Cron jobs ─────────────────────────────────────────────────────────────

    # PSX — daily at 18:30 PST (PSE closes 15:30; yfinance cache settles ~3 h later)
    scheduler.add_job(
        func=_run_pipeline,
        trigger=CronTrigger(hour=18, minute=30, timezone=_TZ),
        args=["psx"],
        id="psx_daily",
        name="PSX daily price ingestion",
        replace_existing=True,
        misfire_grace_time=3600,   # 1 h grace — tolerate Streamlit restart during window
    )

    # FX — daily at 09:00 PST (BSP publishes morning reference rates)
    scheduler.add_job(
        func=_run_pipeline,
        trigger=CronTrigger(hour=9, minute=0, timezone=_TZ),
        args=["fx"],
        id="fx_daily",
        name="FX daily rate ingestion",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # BSP — 1st of each month at 08:00 PST
    # Policy decisions are announced monthly; full refresh is lightweight.
    scheduler.add_job(
        func=_run_pipeline,
        trigger=CronTrigger(day=1, hour=8, minute=0, timezone=_TZ),
        args=["bsp"],
        id="bsp_monthly",
        name="BSP monthly policy rate ingestion",
        replace_existing=True,
        misfire_grace_time=86400,  # 24 h grace — monthly cadence allows tolerance
    )

    # ── Interval jobs ─────────────────────────────────────────────────────────

    # Prices — every 6 hours (DA/NFA bulletins update intra-day)
    scheduler.add_job(
        func=_run_pipeline,
        trigger=IntervalTrigger(hours=6, timezone=_TZ),
        args=["prices"],
        id="prices_interval",
        name="Prices 6-hour refresh",
        replace_existing=True,
        misfire_grace_time=1800,
    )

    # Sentiment — every 4 hours (Reddit API rate limits constrain shorter cadence)
    scheduler.add_job(
        func=_run_pipeline,
        trigger=IntervalTrigger(hours=4, timezone=_TZ),
        args=["sentiment"],
        id="sentiment_interval",
        name="Sentiment 4-hour refresh",
        replace_existing=True,
        misfire_grace_time=1800,
    )

    scheduler.start()

    jobs = scheduler.get_jobs()
    logger.info(
        "Scheduler started. %d jobs registered: %s",
        len(jobs),
        [j.id for j in jobs],
    )
    for job in jobs:
        logger.info(
            "  %s — next run: %s",
            job.id,
            job.next_run_time,
        )
