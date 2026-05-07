"""
Response schemas for the PH-Dashboard FastAPI layer.

Defining these explicitly keeps the API contract stable even as internal
data structures evolve, and lets FastAPI generate accurate OpenAPI docs.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"


class ViewMeta(BaseModel):
    """Metadata for a single available view/table."""

    name: str
    type: str = Field(description="'VIEW' or 'BASE TABLE'")
    columns: list[str] = Field(default_factory=list)


class ViewsResponse(BaseModel):
    views: list[ViewMeta]
    total: int


class DataResponse(BaseModel):
    """Tabular result from GET /data."""

    view: str
    columns: list[str]
    rows: list[dict[str, Any]]
    total_rows: int
    truncated: bool = Field(
        description="True when the server applied a row cap and the full result set is larger."
    )
    filters_applied: dict[str, Any] = Field(default_factory=dict)


class QueryResponse(BaseModel):
    """Result of POST /query."""

    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    execution_ms: Optional[float] = None


class KPIStat(BaseModel):
    title: str
    value: str
    raw: Optional[float] = None
    change_pct: Optional[float] = None
    trend: str = Field(description="'up', 'down', or 'neutral'")


class KPIResponse(BaseModel):
    view: str
    stats: list[KPIStat]


class ErrorResponse(BaseModel):
    detail: str
    error_type: str = "api_error"
