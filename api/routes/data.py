"""
Data routes for the PH-Dashboard API.

All heavy lifting is delegated to api.services.query_service so that
these route handlers stay thin: validate → call service → return response.

Endpoints
---------
GET  /views              List all available DuckDB views / tables.
GET  /data               Fetch rows from a named view with optional filters.
POST /query              Run a validated SELECT statement.
GET  /kpi/{view}         Return four summary KPI stats for a view.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from api.schemas import (
    DataResponse,
    KPIResponse,
    KPIStat,
    QueryRequest,
    QueryResponse,
    ViewMeta,
    ViewsResponse,
)
from api.services import (
    compute_kpis,
    fetch_view,
    get_view_columns,
    list_views,
    run_query,
)
from lib.views import ALLOWED_VIEWS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["data"])

# _ALLOWED_VIEWS is now derived from lib.views.ALLOWED_VIEWS (single source of truth).
# Adding a new pipeline only requires updating db/init.py::REQUIRED_OBJECTS and
# lib/views.py::VIEW_AXIS_HINTS — this file needs no manual change.
_ALLOWED_VIEWS: frozenset[str] = ALLOWED_VIEWS


def _assert_view_allowed(view: str) -> None:
    """Raise 404 if *view* is not in the allowed set."""
    if view not in _ALLOWED_VIEWS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"View '{view}' not found. Call GET /views for the full list.",
        )


def _assert_column_allowed(view: str, col: str) -> None:
    """
    Raise 400 if *col* is not a real column in *view*.

    Prevents SQL injection via the date_col / value_col query parameters,
    which cannot be parameterised in DuckDB (column names are not bind values).
    Cost: one 'SELECT * FROM view LIMIT 0' round-trip — negligible for a local DB.
    """
    try:
        valid = set(get_view_columns(view))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not inspect view '{view}': {exc}") from exc
    if col not in valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Column '{col}' does not exist in view '{view}'. Valid columns: {sorted(valid)}",
        )


# ---------------------------------------------------------------------------
# GET /views
# ---------------------------------------------------------------------------

@router.get(
    "/views",
    response_model=ViewsResponse,
    summary="List available datasets",
)
async def get_views() -> ViewsResponse:
    """
    Return all tables and views registered in the DuckDB 'main' schema,
    together with their column names.

    The React frontend uses this to populate the view selector and the
    SQL editor's schema browser.
    """
    try:
        raw = list_views()
    except Exception as exc:
        logger.exception("Failed to list views")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    metas: list[ViewMeta] = []
    for entry in raw:
        name = entry["name"]
        try:
            cols = get_view_columns(name)
        except Exception:
            cols = []
        metas.append(ViewMeta(name=name, type=entry["type"], columns=cols))

    return ViewsResponse(views=metas, total=len(metas))


# ---------------------------------------------------------------------------
# GET /data
# ---------------------------------------------------------------------------

@router.get(
    "/data",
    response_model=DataResponse,
    summary="Fetch dataset rows",
)
async def get_data(
    view: str = Query(..., description="Name of the DuckDB view to query."),
    date_col: Optional[str] = Query(
        default=None,
        description="Column to apply the date range filter on.",
    ),
    start: Optional[str] = Query(
        default=None,
        description="Start date (ISO-8601, e.g. 2023-01-01). Requires date_col.",
    ),
    end: Optional[str] = Query(
        default=None,
        description="End date (ISO-8601, e.g. 2024-12-31). Requires date_col.",
    ),
    limit: int = Query(
        default=1_000,
        ge=1,
        le=10_000,
        description="Maximum rows to return.",
    ),
) -> DataResponse:
    """
    Fetch rows from a named view, with optional date-range filtering.

    When ``date_col``, ``start``, and ``end`` are all supplied, a
    ``WHERE CAST(date_col AS DATE) BETWEEN start AND end`` clause is added.
    Omit any one of the three to skip filtering entirely.
    """
    _assert_view_allowed(view)
    if date_col and start and end:
        _assert_column_allowed(view, date_col)

    try:
        result = fetch_view(
            view,
            date_col=date_col,
            start=start,
            end=end,
            limit=limit,
        )
    except Exception as exc:
        logger.exception("fetch_view failed for view=%s", view)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return DataResponse(**result)


# ---------------------------------------------------------------------------
# POST /query
# ---------------------------------------------------------------------------

@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Execute a custom SELECT query",
)
async def post_query(body: QueryRequest) -> QueryResponse:
    """
    Execute a user-supplied SQL SELECT statement against the local DuckDB.

    **Security constraints:**
    - Only ``SELECT`` statements are accepted (validated by ``QueryRequest``).
    - Results are capped at ``limit`` rows (max 10,000) server-side.
    - DuckDB is opened read-only — no writes are possible.

    This endpoint powers the SQL editor in the React frontend.
    """
    try:
        result = run_query(body.sql, limit=body.limit or 1_000)
    except Exception as exc:
        logger.exception("run_query failed")
        # Surface the DuckDB error message to help the client fix their query.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Query execution error: {exc}",
        ) from exc

    return QueryResponse(**result)


# ---------------------------------------------------------------------------
# GET /kpi/{view}
# ---------------------------------------------------------------------------

@router.get(
    "/kpi/{view}",
    response_model=KPIResponse,
    summary="Get summary KPI stats for a view",
)
async def get_kpi(
    view: str,
    value_col: Optional[str] = Query(
        default=None,
        description=(
            "Numeric column to derive KPIs from. "
            "When omitted the service auto-selects the first suitable numeric column."
        ),
    ),
) -> KPIResponse:
    """
    Compute four summary statistics (Latest, Maximum, Minimum, Average)
    from a view's primary numeric column.

    The React frontend uses this to populate the KPI card strip above
    each chart without having to compute stats client-side.
    """
    _assert_view_allowed(view)
    if value_col:
        _assert_column_allowed(view, value_col)

    try:
        stats_raw = compute_kpis(view, value_col=value_col)
    except Exception as exc:
        logger.exception("compute_kpis failed for view=%s", view)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return KPIResponse(
        view=view,
        stats=[KPIStat(**s) for s in stats_raw],
    )
