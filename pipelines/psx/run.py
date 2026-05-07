"""
PSX pipeline entry point.

Orchestrates: extract → transform → load

Can be invoked three ways:
  1. Direct import:    from pipelines.psx.run import run; run()
  2. Module execution: python -m pipelines.psx.run
  3. APScheduler:      scheduler calls run() via importlib
"""

from __future__ import annotations

import logging
import sys

from pipelines.psx.extract   import extract
from pipelines.psx.transform import transform
from pipelines.psx.load      import load

logger = logging.getLogger(__name__)


def run() -> None:
    logger.info("=== PSX pipeline start ===")
    try:
        extract()
        transform()
        load()
        logger.info("=== PSX pipeline complete ===")
    except Exception as exc:
        logger.error("=== PSX pipeline FAILED: %s ===", exc)
        raise


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    try:
        run()
    except Exception:
        sys.exit(1)
    sys.exit(0)