"""
GET /status — pipeline data-source status for the frontend disclosure banner.

For each pipeline, returns:
  - last_run:   ISO timestamp of the most recent pipeline_runs entry
  - last_status: 'success' | 'error' | 'never'
  - synthetic:  True when the pipeline is currently running on generated data
                (credentials absent, CSV not provided, etc.)

The Next.js frontend renders a yellow ⚠ banner on any view whose backing
pipeline is in synthetic mode, ensuring the analyst never mistakes
generated data for a live market signal.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from lib.db import get_read_conn
from lib.views import synthetic_status

logger = logging.getLogger(__name__)

router = APIRouter(tags=["meta"])


class PipelineStatus(BaseModel):
    pipeline: str
    last_run: str | None
    last_status: str          # 'success' | 'error' | 'never'
    synthetic: bool


class StatusResponse(BaseModel):
    pipelines: list[PipelineStatus]


@router.get(
    "/status",
    response_model=StatusResponse,
    summary="Per-pipeline data-source status and synthetic-data disclosure",
)
async def get_status() -> StatusResponse:
    """
    Return runtime status for every registered pipeline.

    'synthetic: true' means the pipeline is using generated/fallback data
    because a required credential or file is absent from the environment.
    The frontend should display a disclosure banner for any view backed by
    a synthetic pipeline.
    """
    synth_map = synthetic_status()

    try:
        with get_read_conn() as con:
            rows = con.execute(
                """
                SELECT
                    pipeline,
                    MAX(run_at)                                         AS last_run,
                    MAX_BY(status, run_at)                              AS last_status
                FROM pipeline_runs
                GROUP BY pipeline
                ORDER BY pipeline
                """
            ).fetchall()
        run_map: dict[str, tuple[str, str]] = {
            r[0]: (r[1].isoformat() if hasattr(r[1], "isoformat") else str(r[1]), r[2])
            for r in rows
        }
    except Exception as exc:
        logger.warning("Could not query pipeline_runs: %s", exc)
        run_map = {}

    pipelines = []
    for pipeline, is_synthetic in synth_map.items():
        run_info = run_map.get(pipeline)
        pipelines.append(
            PipelineStatus(
                pipeline=pipeline,
                last_run=run_info[0] if run_info else None,
                last_status=run_info[1] if run_info else "never",
                synthetic=is_synthetic,
            )
        )

    return StatusResponse(pipelines=pipelines)
