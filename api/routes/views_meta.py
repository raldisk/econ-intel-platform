"""
GET /views/meta — serves axis hints and the allowed view list to the Next.js client.

This endpoint is the reason the frontend no longer needs a hardcoded VIEWS array
or VIEW_AXIS_HINTS constant.  When a new pipeline is added:
  1. Add to db/init.py::REQUIRED_OBJECTS
  2. Add to lib/views.py::VIEW_AXIS_HINTS
  The Next.js view selector and chart defaults update automatically on next page load.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from lib.views import ALLOWED_VIEWS, VIEW_AXIS_HINTS

router = APIRouter(tags=["meta"])


class ViewAxisHint(BaseModel):
    date_col: str
    value_col: str


class ViewsMetaResponse(BaseModel):
    views: list[str]
    hints: dict[str, ViewAxisHint]


@router.get(
    "/views/meta",
    response_model=ViewsMetaResponse,
    summary="View registry with axis hints for the frontend",
)
async def get_views_meta() -> ViewsMetaResponse:
    """
    Return the canonical list of allowed views and their chart axis defaults.

    The Next.js explorer workspace fetches this on mount and uses it to:
      - Populate the view selector sidebar
      - Set the default x-axis (date) and y-axis (value) columns per view
      - Derive chart labels

    Replaces the hardcoded VIEWS array and VIEW_AXIS_HINTS constant
    previously duplicated inside explorer-workspace.tsx.
    """
    views_sorted = sorted(ALLOWED_VIEWS)
    hints = {
        view: ViewAxisHint(**hint)
        for view, hint in VIEW_AXIS_HINTS.items()
        if view in ALLOWED_VIEWS
    }
    return ViewsMetaResponse(views=views_sorted, hints=hints)
