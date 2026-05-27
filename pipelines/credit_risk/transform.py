"""
credit_risk/transform.py
========================
Normalise a CreditExposureRecord (or None) into a pandas DataFrame
matching the credit_exposure DuckDB view schema.

Empty schema written when record is None — DuckDB view registers but
returns zero rows. No crash, no missing columns.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from pipelines.credit_risk.extract import CreditExposureRecord

# ---------------------------------------------------------------------------
# Canonical schema — all columns that credit_exposure view must expose.
# Empty frame uses these dtypes so DuckDB schema inference is stable.
# ---------------------------------------------------------------------------

_SCHEMA: dict = {
    "period_key":              pd.Series(dtype="str"),
    "outstanding_balance_usd": pd.Series(dtype="float64"),
    "npl_count":               pd.Series(dtype="int64"),
    "total_rwa_usd":           pd.Series(dtype="float64"),
    "total_provisions_usd":    pd.Series(dtype="float64"),
    "facility_count":          pd.Series(dtype="int64"),
    "submitted_at":            pd.Series(dtype="str"),
}


def transform(record: Optional[CreditExposureRecord]) -> pd.DataFrame:
    """
    Convert CreditExposureRecord to DataFrame.

    Args:
        record: Populated record or None (when upstream unavailable).

    Returns:
        Single-row DataFrame on success, empty DataFrame on None.
        Schema is always consistent — downstream load.py can read_parquet safely.
    """
    if record is None:
        return pd.DataFrame(_SCHEMA)

    return pd.DataFrame([{
        "period_key":              record.period_key,
        "outstanding_balance_usd": record.outstanding_balance_usd,
        "npl_count":               record.npl_count,
        "total_rwa_usd":           record.total_rwa_usd,
        "total_provisions_usd":    record.total_provisions_usd,
        "facility_count":          record.facility_count,
        "submitted_at":            record.submitted_at,
    }])
