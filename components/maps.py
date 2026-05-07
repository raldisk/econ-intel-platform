"""
components/maps.py — Philippine regional map helpers.

True choropleth requires a GeoJSON boundary file for PSA administrative
regions. That file is not bundled with the dashboard (large binary asset).
This module provides:

  1. ph_region_bar() — horizontal bar chart ranked by value (always works)
  2. ph_choropleth()  — Plotly choropleth using the bundled GeoJSON if
                        GEOJSON_PATH is set in config.py; falls back to
                        ph_region_bar() silently if the file is absent.

Usage:
    from components.maps import ph_region_bar, ph_choropleth
    fig = ph_choropleth(df, region_col="region",
                        value_col="gini_coefficient",
                        title="Gini Coefficient by Region")
    st.plotly_chart(fig, use_container_width=True)

GeoJSON setup (optional):
    Download the PSA administrative boundaries GeoJSON from:
    https://github.com/faeldon/philippines-json-maps
    Place at data/geojson/ph_regions.geojson and set in config.py:
        GEOJSON_PATH = DATA_RAW / "geojson" / "ph_regions.geojson"
    The property key that matches region names is "REGION".
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from components.charts import COLORS, _apply_layout

logger = logging.getLogger(__name__)

# PSA administrative region display order (south to north for bar chart)
PSA_REGION_ORDER = [
    "BARMM",
    "Region XIII - Caraga",
    "Region XII - SOCCSKSARGEN",
    "Region XI - Davao Region",
    "Region X - Northern Mindanao",
    "Region IX - Zamboanga Peninsula",
    "Region VIII - Eastern Visayas",
    "Region VII - Central Visayas",
    "Region VI - Western Visayas",
    "Region V - Bicol Region",
    "Region IV-B - MIMAROPA",
    "Region IV-A - CALABARZON",
    "Region III - Central Luzon",
    "Region II - Cagayan Valley",
    "Region I - Ilocos Region",
    "CAR",
    "NCR",
]


def ph_region_bar(
    df: pd.DataFrame,
    region_col: str,
    value_col: str,
    title: str = "",
    color: str = "regional",
    value_suffix: str = "",
    sort_ascending: bool = True,
) -> go.Figure:
    """
    Horizontal bar chart of a regional metric.
    Sorted by value by default — override with sort_ascending=False
    to preserve PSA region order.
    """
    if sort_ascending:
        df_plot = df.sort_values(value_col, ascending=True).copy()
    else:
        # Preserve PSA canonical order
        order_map = {r: i for i, r in enumerate(reversed(PSA_REGION_ORDER))}
        df_plot = df.copy()
        df_plot["_order"] = df_plot[region_col].map(order_map).fillna(99)
        df_plot = df_plot.sort_values("_order").drop(columns=["_order"])

    fig = go.Figure(go.Bar(
        x=df_plot[value_col],
        y=df_plot[region_col],
        orientation="h",
        marker_color=COLORS.get(color, COLORS["regional"]),
        text=df_plot[value_col].round(4).astype(str) + value_suffix,
        textposition="outside",
    ))
    fig.update_layout(
        height=max(320, len(df_plot) * 24),
        xaxis_ticksuffix=value_suffix,
    )
    return _apply_layout(fig, title)


def ph_choropleth(
    df: pd.DataFrame,
    region_col: str,
    value_col: str,
    title: str = "",
    colorscale: str = "Greens",
    geojson_path: Optional[Path] = None,
) -> go.Figure:
    """
    Choropleth map of a regional metric.

    If geojson_path is None or the file does not exist, falls back to
    ph_region_bar() silently — the calling page never needs to handle
    the missing-file case.
    """
    # Attempt to resolve geojson_path from config if not passed
    if geojson_path is None:
        try:
            import config as cfg
            geojson_path = getattr(cfg, "GEOJSON_PATH", None)
        except Exception:
            pass

    if geojson_path is None or not Path(geojson_path).exists():
        logger.debug(
            "ph_choropleth: GeoJSON not found at %s — using bar fallback.",
            geojson_path,
        )
        return ph_region_bar(df, region_col, value_col, title)

    try:
        geojson = json.loads(Path(geojson_path).read_text(encoding="utf-8"))
        fig = px.choropleth(
            df,
            geojson=geojson,
            locations=region_col,
            featureidkey="properties.REGION",
            color=value_col,
            color_continuous_scale=colorscale,
            title=title,
        )
        fig.update_geos(fitbounds="locations", visible=False)
        return _apply_layout(fig, title)
    except Exception as exc:
        logger.warning("ph_choropleth: GeoJSON render failed (%s) — bar fallback.", exc)
        return ph_region_bar(df, region_col, value_col, title)
