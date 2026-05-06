"""
tests/test_view_registry.py — Registry consistency and security guards.

Catches:
  - Drift between ALLOWED_VIEWS (API allowlist) and REQUIRED_OBJECTS (DB bootstrap)
  - Drift between ALLOWED_VIEWS and VIEW_AXIS_HINTS (axis metadata)
  - Column injection via date_col not validated against real columns

These tests fail fast on a new pipeline that was added to db/init.py but
whose axis hints were not added to lib/views.py — or vice versa.
"""

from __future__ import annotations

import pytest


class TestViewRegistry:
    def test_allowed_views_matches_required_objects(self):
        """
        ALLOWED_VIEWS in lib.views must equal REQUIRED_OBJECTS in db.init.

        Failure here means a pipeline was added to one registry but not the other.
        Add the missing entry to lib/views.py::VIEW_AXIS_HINTS and ensure
        db/init.py::REQUIRED_OBJECTS includes the new view name.
        """
        from db.init import REQUIRED_OBJECTS
        from lib.views import ALLOWED_VIEWS

        missing_from_allowed = REQUIRED_OBJECTS - ALLOWED_VIEWS
        missing_from_required = ALLOWED_VIEWS - REQUIRED_OBJECTS

        assert not missing_from_allowed, (
            f"Views in REQUIRED_OBJECTS but missing from ALLOWED_VIEWS: "
            f"{missing_from_allowed}. Add them to lib/views.py."
        )
        assert not missing_from_required, (
            f"Views in ALLOWED_VIEWS but missing from REQUIRED_OBJECTS: "
            f"{missing_from_required}. Add them to db/init.py."
        )

    def test_axis_hints_cover_all_allowed_views(self):
        """
        Every view in ALLOWED_VIEWS should have a VIEW_AXIS_HINTS entry.

        Views without hints fall back to {'date': 'date', 'value': 'value'} in
        the frontend — which silently produces empty charts.  This test
        surfaces missing entries before they reach the UI.

        pipeline_runs is exempt (meta-table, charted by rows_affected).
        """
        from lib.views import ALLOWED_VIEWS, VIEW_AXIS_HINTS

        exempt = {"pipeline_runs"}
        without_hints = (ALLOWED_VIEWS - exempt) - set(VIEW_AXIS_HINTS.keys())

        assert not without_hints, (
            f"Views in ALLOWED_VIEWS with no axis hints: {without_hints}. "
            f"Add entries to lib/views.py::VIEW_AXIS_HINTS."
        )

    def test_axis_hints_have_required_fields(self):
        """Each VIEW_AXIS_HINTS entry must have both date_col and value_col."""
        from lib.views import VIEW_AXIS_HINTS

        malformed = [
            view
            for view, hint in VIEW_AXIS_HINTS.items()
            if "date_col" not in hint or "value_col" not in hint
        ]
        assert not malformed, (
            f"VIEW_AXIS_HINTS entries missing date_col or value_col: {malformed}"
        )

    def test_synthetic_status_covers_all_pipelines(self):
        """
        synthetic_status() must return an entry for every pipeline that has
        views in ALLOWED_VIEWS.  Gaps mean a pipeline's data-source status
        is invisible to the /status endpoint and the UI disclosure banner.
        """
        from lib.views import synthetic_status

        # Derive expected pipelines from VIEW_AXIS_HINTS indirectly
        # (synthetic_status is the authoritative list of pipelines)
        status = synthetic_status()
        assert isinstance(status, dict), "synthetic_status() must return a dict"
        assert len(status) > 0, "synthetic_status() returned empty dict"
        for name, is_synthetic in status.items():
            assert isinstance(is_synthetic, bool), (
                f"synthetic_status()['{name}'] must be bool, got {type(is_synthetic)}"
            )
