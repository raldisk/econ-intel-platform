"""
Shared DuckDB connection helpers for PH-Dashboard.

USAGE RULES:
  - App code (Streamlit, Dash) ALWAYS uses get_read_conn() — never duckdb.connect() directly.
  - Pipeline load.py files use get_write_conn() — they own the read-write lock.
  - Do NOT hold a connection open across Streamlit re-renders. Open, query, close.

WHY read_only FOR APPS:
  DuckDB allows only one read-write connection per database file at a time.
  Running both Streamlit and Dash simultaneously with read-write connections
  raises IOException on the second process. Read-only connections have no
  such constraint.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

import duckdb

import config as cfg


@contextmanager
def get_read_conn() -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """
    Context manager that yields a read-only DuckDB connection.
    For use in Streamlit/Dash query callbacks — always closes the connection.

    Example:
        with get_read_conn() as con:
            df = con.execute("SELECT * FROM psx_prices LIMIT 100").df()
    """
    con = duckdb.connect(str(cfg.DB_PATH), read_only=True)
    try:
        yield con
    finally:
        con.close()


@contextmanager
def get_write_conn() -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """
    Context manager that yields a read-write DuckDB connection.
    For use in pipeline load.py files ONLY — not in app code.

    Only one process should hold a write connection at a time.
    Guard scheduler activation with PH_SCHEDULER_ENABLED env var.
    """
    con = duckdb.connect(str(cfg.DB_PATH))
    try:
        yield con
    finally:
        con.close()