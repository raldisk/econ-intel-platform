"""
scheduler/main.py — Standalone scheduler process.

Run this as a separate terminal session, independent of any frontend:

    python -m scheduler.main

This replaces the former PH_SCHEDULER_ENABLED=true pattern that embedded
APScheduler inside the Streamlit process.  Decoupling means:
  - Pipeline execution survives Streamlit restarts and hot-reloads
  - The write-lock acquired by each pipeline cannot race with Streamlit teardown
  - The scheduler has a clear, auditable lifecycle separate from the UI

Heartbeat
---------
Writes db/scheduler.heartbeat every 60 seconds.
The /status API and the Streamlit sidebar can check this file's mtime
to detect a dead scheduler without needing a network call.

Stop with Ctrl-C — the atexit handler removes the heartbeat file cleanly.
"""

from __future__ import annotations

import atexit
import logging
import logging.handlers
import signal
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging — mirrors api/main.py setup, writes to scheduler/logs/
# ---------------------------------------------------------------------------
_LOG_DIR = Path(__file__).parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.TimedRotatingFileHandler(
            _LOG_DIR / "scheduler.log",
            when="midnight",
            backupCount=14,
            encoding="utf-8",
        ),
    ],
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Heartbeat file
# ---------------------------------------------------------------------------
_HEARTBEAT = Path(__file__).parent.parent / "db" / "scheduler.heartbeat"


def _write_heartbeat() -> None:
    try:
        _HEARTBEAT.write_text(str(time.time()))
    except OSError as exc:
        logger.debug("Heartbeat write failed (non-fatal): %s", exc)


def _remove_heartbeat() -> None:
    try:
        _HEARTBEAT.unlink(missing_ok=True)
    except OSError:
        pass


atexit.register(_remove_heartbeat)


# ---------------------------------------------------------------------------
# Signal handling (Ctrl-C and kill)
# ---------------------------------------------------------------------------
def _handle_signal(signum, frame):  # noqa: ANN001
    logger.info("Received signal %s — shutting down scheduler.", signum)
    sys.exit(0)


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    logger.info("PH-Dashboard scheduler starting (standalone process).")

    from scheduler.cron_jobs import start_scheduler
    start_scheduler()
    logger.info("Scheduler started. Heartbeat interval: 60s. Stop with Ctrl-C.")

    while True:
        _write_heartbeat()
        time.sleep(60)


if __name__ == "__main__":
    main()
