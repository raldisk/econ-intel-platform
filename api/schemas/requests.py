"""
Request schemas for the PH-Dashboard FastAPI layer.

All inbound payloads are validated here before reaching service code.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class QueryRequest(BaseModel):
    """Body schema for POST /query."""

    sql: str = Field(
        ...,
        min_length=1,
        max_length=8_000,
        description="A read-only SQL SELECT statement to execute against the local DuckDB.",
        examples=["SELECT * FROM psx_prices LIMIT 100"],
    )
    limit: Optional[int] = Field(
        default=1_000,
        ge=1,
        le=10_000,
        description="Maximum rows to return. Applied as a server-side cap even if the query has no LIMIT.",
    )

    @field_validator("sql")
    @classmethod
    def must_be_select(cls, v: str) -> str:
        """
        Reject any statement that isn't a plain SELECT.

        Strategy: strip leading whitespace and SQL block comments (-- …),
        then check that the first meaningful keyword is SELECT. This blocks
        INSERT, UPDATE, DELETE, DROP, CREATE, PRAGMA, ATTACH, COPY, and the
        like without maintaining an explicit denylist.
        """
        stripped = v.strip()
        # Remove leading line comments so "-- comment\nSELECT …" still passes.
        lines = [
            line for line in stripped.splitlines()
            if not line.strip().startswith("--")
        ]
        first_token = " ".join(lines).strip().split()[0].upper() if lines else ""
        if first_token != "SELECT":
            raise ValueError(
                "Only SELECT statements are permitted. "
                f"Received statement beginning with: {first_token!r}"
            )
        return stripped
