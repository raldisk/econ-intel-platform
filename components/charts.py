"""
components/charts.py — shared Plotly figure factories.

All figures use a transparent background and zero margin so they embed
cleanly into Streamlit columns regardless of theme. Color palette is
consistent across all pages and keyed by domain.

Usage:
    from components.charts import line, bar, area, scatter, heatmap_table
    fig = line(df, x="period_date", y="cpi_index", title="CPI Index")
    st.plotly_chart(fig, use_container_width=True)
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ---------------------------------------------------------------------------
# Brand palette
# ---------------------------------------------------------------------------

COLORS = {
    "psx":         "#185FA5",   # PSX / markets — deep blue
    "bsp":         "#533AB7",   # BSP / monetary — violet
    "fx":          "#0F6E56",   # FX — teal
    "gdp":         "#1D9E75",   # GDP — green
    "cpi":         "#BA7517",   # CPI — amber
    "inflation":   "#E24B4A",   # Inflation — red
    "remittance":  "#533AB7",   # OFW remittances — violet
    "labor":       "#1B7EC2",   # Labor — blue
    "prices":      "#D4841A",   # Commodity prices — orange
    "fuel":        "#6B6563",   # Fuel — dark grey
    "regional":    "#2E8B57",   # Regional / Gini — sea green
    "sentiment":   "#9B59B6",   # Sentiment — purple
    "positive":    "#27AE60",   # Positive sentiment
    "negative":    "#E74C3C",   # Negative sentiment
    "neutral":     "#95A5A6",   # Neutral / reference lines
    "coa":         "#2C3E50",   # COA / budget — dark navy
    "secondary":   "#AAAAAA",   # Secondary series
}

_LAYOUT = dict(
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    margin=dict(l=0, r=0, t=28, b=0),
    font=dict(size=12),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
)


def _apply_layout(fig: go.Figure, title: str = "", yaxis_suffix: str = "") -> go.Figure:
    layout = dict(_LAYOUT)
    if title:
        layout["title"] = dict(text=title, font=dict(size=13), x=0, xanchor="left")
    if yaxis_suffix:
        layout["yaxis"] = dict(ticksuffix=yaxis_suffix)
    fig.update_layout(**layout)
    return fig


# ---------------------------------------------------------------------------
# Line chart
# ---------------------------------------------------------------------------

def line(
    df: pd.DataFrame,
    x: str,
    y: str | list[str],
    color: str = "psx",
    title: str = "",
    yaxis_suffix: str = "",
    zero_line: bool = False,
    labels: Optional[dict] = None,
) -> go.Figure:
    """Single or multi-series line chart."""
    ys = [y] if isinstance(y, str) else y
    fig = go.Figure()
    for i, col in enumerate(ys):
        palette_key = col if col in COLORS else color
        c = COLORS.get(palette_key, COLORS["psx"])
        fig.add_trace(go.Scatter(
            x=df[x], y=df[col],
            mode="lines+markers",
            name=labels.get(col, col) if labels else col,
            line=dict(color=c, width=2),
            marker=dict(size=4),
        ))
    if zero_line:
        fig.add_hline(y=0, line_dash="dot", line_color=COLORS["neutral"])
    return _apply_layout(fig, title, yaxis_suffix)


# ---------------------------------------------------------------------------
# Bar chart
# ---------------------------------------------------------------------------

def bar(
    df: pd.DataFrame,
    x: str,
    y: str,
    color: str = "psx",
    title: str = "",
    yaxis_suffix: str = "",
    color_by_sign: bool = False,
) -> go.Figure:
    """Vertical bar chart. color_by_sign colours positive/negative bars."""
    if color_by_sign and y in df.columns:
        bar_colors = [COLORS["positive"] if v >= 0 else COLORS["negative"]
                      for v in df[y].fillna(0)]
    else:
        bar_colors = COLORS.get(color, COLORS["psx"])

    fig = go.Figure(go.Bar(
        x=df[x], y=df[y],
        marker_color=bar_colors,
        name=y,
    ))
    return _apply_layout(fig, title, yaxis_suffix)


# ---------------------------------------------------------------------------
# Area chart
# ---------------------------------------------------------------------------

def area(
    df: pd.DataFrame,
    x: str,
    y: str,
    color: str = "psx",
    title: str = "",
    yaxis_suffix: str = "",
) -> go.Figure:
    """Filled area chart."""
    c = COLORS.get(color, COLORS["psx"])
    fig = go.Figure(go.Scatter(
        x=df[x], y=df[y],
        fill="tozeroy",
        mode="lines",
        line=dict(color=c, width=1.5),
        fillcolor=c.replace(")", ", 0.15)").replace("rgb", "rgba") if c.startswith("rgb") else c,
        name=y,
    ))
    return _apply_layout(fig, title, yaxis_suffix)


# ---------------------------------------------------------------------------
# Dual-axis line chart
# ---------------------------------------------------------------------------

def dual_axis(
    df: pd.DataFrame,
    x: str,
    y1: str,
    y2: str,
    color1: str = "psx",
    color2: str = "cpi",
    title: str = "",
    y1_suffix: str = "",
    y2_suffix: str = "",
    labels: Optional[dict] = None,
) -> go.Figure:
    """Two series on independent y-axes — useful for rate vs price overlays."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    lbl1 = labels.get(y1, y1) if labels else y1
    lbl2 = labels.get(y2, y2) if labels else y2
    fig.add_trace(go.Scatter(
        x=df[x], y=df[y1], name=lbl1,
        line=dict(color=COLORS.get(color1, COLORS["psx"]), width=2),
    ), secondary_y=False)
    fig.add_trace(go.Scatter(
        x=df[x], y=df[y2], name=lbl2,
        line=dict(color=COLORS.get(color2, COLORS["cpi"]), width=2, dash="dot"),
    ), secondary_y=True)
    fig.update_yaxes(ticksuffix=y1_suffix, secondary_y=False)
    fig.update_yaxes(ticksuffix=y2_suffix, secondary_y=True)
    return _apply_layout(fig, title)


# ---------------------------------------------------------------------------
# OHLCV candlestick
# ---------------------------------------------------------------------------

def candlestick(
    df: pd.DataFrame,
    date_col: str = "date",
    title: str = "",
) -> go.Figure:
    """Standard OHLCV candlestick. Expects open/high/low/close columns."""
    fig = go.Figure(go.Candlestick(
        x=df[date_col],
        open=df["open"], high=df["high"],
        low=df["low"],   close=df["close"],
        increasing_line_color=COLORS["gdp"],
        decreasing_line_color=COLORS["inflation"],
        name="OHLCV",
    ))
    fig.update_layout(xaxis_rangeslider_visible=False)
    return _apply_layout(fig, title)


# ---------------------------------------------------------------------------
# Scatter / correlation
# ---------------------------------------------------------------------------

def scatter(
    df: pd.DataFrame,
    x: str,
    y: str,
    color_col: Optional[str] = None,
    size_col: Optional[str] = None,
    title: str = "",
    trendline: bool = True,
    labels: Optional[dict] = None,
) -> go.Figure:
    """Scatter plot with optional trendline."""
    kwargs: dict = dict(x=x, y=y, title=title, labels=labels or {})
    if color_col:
        kwargs["color"] = color_col
    if size_col:
        kwargs["size"] = size_col
    if trendline:
        kwargs["trendline"] = "ols"
    fig = px.scatter(df, **kwargs)
    return _apply_layout(fig)


# ---------------------------------------------------------------------------
# Choropleth — Philippine regions
# ---------------------------------------------------------------------------

def ph_choropleth(
    df: pd.DataFrame,
    region_col: str,
    value_col: str,
    title: str = "",
    colorscale: str = "Greens",
) -> go.Figure:
    """
    Regional choropleth using PSA region names.
    Uses a simple bar chart as a fallback — true choropleth requires
    a GeoJSON boundary file (not bundled; Phase 9 uses bar fallback).
    """
    df_sorted = df.sort_values(value_col, ascending=True)
    fig = go.Figure(go.Bar(
        x=df_sorted[value_col],
        y=df_sorted[region_col],
        orientation="h",
        marker_color=COLORS["regional"],
        name=value_col,
    ))
    fig.update_layout(
        xaxis_title=value_col,
        yaxis_title="Region",
        height=max(300, len(df_sorted) * 22),
    )
    return _apply_layout(fig, title)


# ---------------------------------------------------------------------------
# Sentiment stacked bar
# ---------------------------------------------------------------------------

def sentiment_stack(
    df: pd.DataFrame,
    x: str = "obs_date",
    title: str = "Daily Sentiment Distribution",
) -> go.Figure:
    """
    Stacked bar for sentiment label distribution over time.
    Expects columns: positive_pct, neutral_pct, negative_pct (or counts).
    """
    fig = go.Figure()
    for label, col, c in [
        ("Positive", "positive", COLORS["positive"]),
        ("Neutral",  "neutral",  COLORS["neutral"]),
        ("Negative", "negative", COLORS["negative"]),
    ]:
        if col in df.columns:
            fig.add_trace(go.Bar(
                x=df[x], y=df[col],
                name=label,
                marker_color=c,
            ))
    fig.update_layout(barmode="stack")
    return _apply_layout(fig, title)
