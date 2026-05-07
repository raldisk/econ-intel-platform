"""
test_bsp_parse.py — unit tests for BSP policy rate parsing.

Mocks the HTTP layer and feeds controlled HTML to the parser.
Asserts:
  - PolicyRate schema (fields present, types correct)
  - Ascending sort applied before direction computation
  - Direction flags correct on known rate sequences
  - Post-parse validation raises ValueError on out-of-range rates
  - Post-parse validation raises ValueError on future dates
  - Empty table returns empty list (not crash)

Run: pytest tests/test_bsp_parse.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import date, timedelta
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.sources.bsp import (
    fetch_policy_rates,
    _parse_bsp_date,
    _parse_rate,
    _validate_policy_rates,
    PolicyRate,
)


# ---------------------------------------------------------------------------
# HTML fixture helpers
# ---------------------------------------------------------------------------

def _bsp_rate_html(rows: list[tuple[str, str, str]]) -> str:
    """
    Build a minimal BSP key rates page HTML fixture.
    rows: list of (date_str, rrp_rate_str, srp_rate_str)
    Order intentionally descending (latest first) — as BSP commonly publishes.
    """
    tr_rows = "\n".join(
        f"<tr><td>{d}</td><td>{rrp}</td><td>{srp}</td></tr>"
        for d, rrp, srp in rows
    )
    return f"""
    <html><body>
    <table>
      <tr><th>Effective Date</th><th>Overnight RRP</th><th>Overnight SRP</th></tr>
      {tr_rows}
    </table>
    </body></html>
    """


# Descending HTML (latest first) — typical BSP page layout
FIXTURE_ROWS_DESC = [
    ("June 20, 2024",     "6.50", "6.50"),
    ("February 15, 2024", "6.50", "6.50"),
    ("November 16, 2023", "6.50", "6.50"),
    ("October 26, 2023",  "6.25", "6.25"),
    ("August 17, 2023",   "6.25", "6.25"),
    ("May 18, 2023",      "6.25", "6.25"),
    ("March 23, 2023",    "6.00", "6.00"),
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def parsed_rates():
    """Parse FIXTURE_ROWS_DESC through fetch_policy_rates() with mocked HTTP."""
    html = _bsp_rate_html(FIXTURE_ROWS_DESC)
    with patch("lib.sources.bsp._get", return_value=html):
        return fetch_policy_rates()


# ---------------------------------------------------------------------------
# Basic schema tests
# ---------------------------------------------------------------------------

def test_returns_list_of_policy_rates(parsed_rates):
    assert isinstance(parsed_rates, list)
    assert len(parsed_rates) > 0
    for r in parsed_rates:
        assert isinstance(r, PolicyRate)


def test_all_fields_present(parsed_rates):
    for r in parsed_rates:
        assert hasattr(r, "decision_date")
        assert hasattr(r, "overnight_rp")
        assert hasattr(r, "overnight_srp")
        assert hasattr(r, "direction")
        assert hasattr(r, "source")


def test_decision_dates_are_date_objects(parsed_rates):
    for r in parsed_rates:
        assert isinstance(r.decision_date, date)


def test_overnight_rp_are_floats(parsed_rates):
    for r in parsed_rates:
        assert isinstance(r.overnight_rp, float)


def test_direction_values_valid(parsed_rates):
    for r in parsed_rates:
        assert r.direction in ("hike", "cut", "hold"), (
            f"Invalid direction: {r.direction} at {r.decision_date}"
        )


# ---------------------------------------------------------------------------
# Sort + direction correctness
# ---------------------------------------------------------------------------

def test_output_sorted_ascending_by_date(parsed_rates):
    """fetch_policy_rates() must return records ascending regardless of HTML order."""
    dates = [r.decision_date for r in parsed_rates]
    assert dates == sorted(dates), (
        "Records not in ascending date order — sort before direction computation failed"
    )


def test_first_record_direction_is_hold(parsed_rates):
    """First record has no prior — must be 'hold' by definition."""
    assert parsed_rates[0].direction == "hold"


def test_direction_hike_when_rate_increases(parsed_rates):
    """
    From fixture: March 2023 (6.00) → October 2023 (6.25) is a hike.
    Confirm the October record is labeled 'hike'.
    """
    # Find the record where rate becomes 6.25 (first occurrence after 6.00)
    rate_sequence = [(r.overnight_rp, r.direction) for r in parsed_rates]
    # First hike from 6.00 → 6.25
    hike_records = [r for r in parsed_rates
                    if r.direction == "hike" and abs(r.overnight_rp - 6.25) < 0.01]
    assert len(hike_records) >= 1, (
        f"Expected at least one 'hike' record at 6.25. Got: {rate_sequence}"
    )


def test_direction_hold_when_rate_unchanged(parsed_rates):
    """Multiple consecutive 6.50 rates should be labeled 'hold'."""
    holds_at_650 = [
        r for r in parsed_rates
        if r.direction == "hold" and abs(r.overnight_rp - 6.50) < 0.01
    ]
    assert len(holds_at_650) >= 1, "Expected hold records at 6.50"


# ---------------------------------------------------------------------------
# Post-parse validation
# ---------------------------------------------------------------------------

def test_validate_raises_on_rate_below_minimum():
    bad = [PolicyRate(date(2024, 1, 1), 0.0, None, "hold")]
    with pytest.raises(ValueError, match="out of plausible range"):
        _validate_policy_rates(bad)


def test_validate_raises_on_rate_above_maximum():
    bad = [PolicyRate(date(2024, 1, 1), 25.0, None, "hold")]
    with pytest.raises(ValueError, match="out of plausible range"):
        _validate_policy_rates(bad)


def test_validate_raises_on_unknown_direction():
    bad = [PolicyRate(date(2024, 1, 1), 6.5, None, "unknown")]
    with pytest.raises(ValueError, match="Unknown BSP direction"):
        _validate_policy_rates(bad)


def test_validate_raises_on_future_date():
    future = date.today() + timedelta(days=10)
    bad = [PolicyRate(future, 6.5, None, "hold")]
    with pytest.raises(ValueError, match="in the future"):
        _validate_policy_rates(bad)


def test_validate_passes_on_valid_records(parsed_rates):
    """Validation must not raise on records produced from the fixture."""
    # This would raise if validation is broken — it should be silent.
    _validate_policy_rates(parsed_rates)


# ---------------------------------------------------------------------------
# Empty table
# ---------------------------------------------------------------------------

def test_empty_html_returns_empty_list():
    empty_html = "<html><body><table><tr><th>Date</th></tr></table></body></html>"
    with patch("lib.sources.bsp._get", return_value=empty_html):
        result = fetch_policy_rates()
    assert result == [], f"Expected empty list, got: {result}"


# ---------------------------------------------------------------------------
# Parse helpers
# ---------------------------------------------------------------------------

def test_parse_bsp_date_multiple_formats():
    assert _parse_bsp_date("June 20, 2024") == date(2024, 6, 20)
    assert _parse_bsp_date("Jun 20, 2024")  == date(2024, 6, 20)
    assert _parse_bsp_date("06/20/2024")    == date(2024, 6, 20)
    assert _parse_bsp_date("2024-06-20")    == date(2024, 6, 20)
    assert _parse_bsp_date("20-Jun-2024")   == date(2024, 6, 20)
    assert _parse_bsp_date("garbage")       is None
    assert _parse_bsp_date("")              is None


def test_parse_rate_strips_percent_and_commas():
    assert _parse_rate("6.50%")   == 6.50
    assert _parse_rate(" 6.50 ")  == 6.50
    assert _parse_rate("1,000.5") == 1000.5
    assert _parse_rate("-")       is None
    assert _parse_rate("..")      is None
    assert _parse_rate("")        is None
    assert _parse_rate("n/a")     is None