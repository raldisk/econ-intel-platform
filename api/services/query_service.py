"""
QueryService — the single source of truth for DuckDB access in the API layer.

Design rules:
  - Always uses lib.db.get_read_conn() — never opens connections directly.
  - Serialises DataFrames to plain Python dicts so FastAPI can JSON-encode them.
  - Handles NaN / NaT / Timestamp edge cases that break json.dumps.
  - Does NOT duplicate logic already in apps/dash_app.py; that app continues
    to manage its own _query() helper independently.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any, Optional

import pandas as pd

from lib.db import get_read_conn

logger = logging.getLogger(__name__)

_HARD_ROW_LIMIT = 10_000


def _safe_value(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if hasattr(v, "item"):
        return v.item()
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def _df_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {col: _safe_value(row[col]) for col in df.columns}
        for _, row in df.iterrows()
    ]


def list_views() -> list[dict[str, str]]:
    sql = """
        SELECT table_name, table_type
        FROM information_schema.tables
        WHERE table_schema = 'main'
        ORDER BY table_name
    """
    with get_read_conn() as con:
        rows = con.execute(sql).fetchall()
    return [{"name": row[0], "type": row[1]} for row in rows]


def get_view_columns(view: str) -> list[str]:
    """Return column names for a given view without fetching any data rows."""
    sql = f"SELECT * FROM {view} LIMIT 0"  # noqa: S608 — view validated before call
    with get_read_conn() as con:
        result = con.execute(sql)
        return [desc[0] for desc in result.description]


def fetch_view(
    view: str,
    *,
    date_col: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = 1_000,
) -> dict[str, Any]:
    """
    Fetch rows from a named view with optional date filtering.
    date_col is validated against real columns by the route layer before this runs.
    """
    effective_limit = min(limit, _HARD_ROW_LIMIT)

    where = ""
    filters: dict[str, Any] = {}
    if date_col and start and end:
        where = f"WHERE CAST({date_col} AS DATE) BETWEEN '{start}' AND '{end}'"
        filters = {"date_col": date_col, "start": start, "end": end}

    sql = f"SELECT * FROM {view} {where} LIMIT {effective_limit + 1}"  # noqa: S608

    with get_read_conn() as con:
        df = con.execute(sql).df()

    truncated = len(df) > effective_limit
    if truncated:
        df = df.iloc[:effective_limit]

    records = _df_to_records(df)
    return {
        "view": view,
        "columns": list(df.columns),
        "rows": records,
        "total_rows": len(records),
        "truncated": truncated,
        "filters_applied": filters,
    }


def run_query(sql: str, limit: int = 1_000) -> dict[str, Any]:
    """Execute a pre-validated SELECT statement and return results."""
    effective_limit = min(limit, _HARD_ROW_LIMIT)
    wrapped = f"SELECT * FROM ({sql}) AS _q LIMIT {effective_limit + 1}"

    t0 = time.perf_counter()
    with get_read_conn() as con:
        df = con.execute(wrapped).df()
    elapsed_ms = (time.perf_counter() - t0) * 1000

    truncated = len(df) > effective_limit
    if truncated:
        df = df.iloc[:effective_limit]

    records = _df_to_records(df)
    return {
        "columns": list(df.columns),
        "rows": records,
        "row_count": len(records),
        "truncated": truncated,
        "execution_ms": round(elapsed_ms, 2),
    }


def compute_kpis(view: str, value_col: Optional[str] = None) -> list[dict[str, Any]]:
    """
    Derive four summary KPI statistics using native DuckDB aggregation.

    No pandas row iteration. No 2000-row cap. No insertion-order aliasing.
    'Latest' is MAX_BY(value, row_number) — not .iloc[-1].

    value_col is validated against real columns by the route layer before this runs.
    When omitted, auto-selects the first non-id numeric column via
    information_schema (zero data rows fetched).
    """
    # ── 1. Auto-select value column ───────────────────────────────────────
    if value_col is None:
        skip = {"year", "id", "row", "index", "rank", "seq"}
        with get_read_conn() as con:
            type_rows = con.execute(
                """
                SELECT column_name
                FROM   information_schema.columns
                WHERE  table_name = ?
                  AND  data_type IN (
                         'BIGINT','DOUBLE','FLOAT','INTEGER',
                         'DECIMAL','HUGEINT','SMALLINT','TINYINT','UBIGINT'
                       )
                ORDER BY ordinal_position
                """,
                [view],
            ).fetchall()
        candidates = [r[0] for r in type_rows if r[0].lower() not in skip]
        if not candidates:
            return []
        value_col = candidates[0]

    # ── 2. Single DuckDB pass — all four stats ────────────────────────────
    # MAX_BY(v, rn) = value at highest row_number = last inserted (latest).
    # For previous: CASE returns 1 for exactly the second-to-last row (unique
    # by ROW_NUMBER construction), 0 elsewhere — MAX_BY selects that row.
    # Edge: single-row table → max_rn - 1 = 0, no rn matches, CASE all-zeros,
    # MAX_BY returns the only row's value, yielding change_pct = 0. Correct.
    sql = f"""
        WITH ordered AS (
            SELECT
                {value_col}              AS v,
                ROW_NUMBER() OVER ()     AS rn
            FROM {view}
            WHERE {value_col} IS NOT NULL
        ),
        ranked AS (
            SELECT v, rn, MAX(rn) OVER () AS max_rn FROM ordered
        )
        SELECT
            MAX(v)                                                     AS maximum,
            MIN(v)                                                     AS minimum,
            ROUND(AVG(v), 6)                                           AS average,
            MAX_BY(v, rn)                                              AS latest,
            MAX_BY(v, CASE WHEN rn = max_rn - 1 THEN 1 ELSE 0 END)   AS previous
        FROM ranked
    """  # noqa: S608 — view and value_col validated by caller before this runs

    with get_read_conn() as con:
        row = con.execute(sql).fetchone()

    if row is None or row[3] is None:
        return []

    maximum, minimum, average, latest, previous = row

    def _fmt(v: float) -> str:
        if abs(v) >= 1_000_000:
            return f"{v / 1_000_000:.2f}M"
        if abs(v) >= 1_000:
            return f"{v:,.2f}"
        return f"{v:.4f}" if abs(v) < 10 else f"{v:.2f}"

    prev = previous if previous is not None else latest
    change_pct = ((latest - prev) / prev * 100) if prev != 0 else 0.0
    trend = "up" if change_pct > 0 else ("down" if change_pct < 0 else "neutral")

    return [
        {
            "title": "Latest",
            "value": _fmt(latest),
            "raw": float(latest),
            "change_pct": round(float(change_pct), 4),
            "trend": trend,
        },
        {
            "title": "Maximum",
            "value": _fmt(maximum),
            "raw": float(maximum),
            "change_pct": None,
            "trend": "neutral",
        },
        {
            "title": "Minimum",
            "value": _fmt(minimum),
            "raw": float(minimum),
            "change_pct": None,
            "trend": "neutral",
        },
        {
            "title": "Average",
            "value": _fmt(average),
            "raw": float(average),
            "change_pct": None,
            "trend": "neutral",
        },
    ]
