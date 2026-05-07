"""
PH Dashboard — Dash exploratory app (Phase 10).

The power-user / engineer companion to the Streamlit narrative app.
Designed for analysts who need arbitrary date ranges, dynamic axis
swapping, downloadable filtered parquet, and live SQL execution against
the local DuckDB.

Run:
    python -m apps.dash_app
    # or
    python apps/dash_app.py

Opens at http://127.0.0.1:8050

The SQL passthrough panel is the primary interview asset:
it lets you run live cross-dataset queries against duckdb_local.db
without preparing canned examples in advance.
"""

from __future__ import annotations

import io
import traceback
from datetime import date, timedelta

import dash
import dash_bootstrap_components as dbc
import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, State, callback, dash_table, dcc, html

import config as cfg

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VIEWS = [
    "psx_prices", "bsp_policy_rate", "fx_rates", "stg_fx_rates",
    "fx_volatility", "cpi_trend", "gdp_tracker", "remittance_trend",
    "economic_dashboard", "labor_market", "regional_inequality",
    "commodity_prices", "food_price_decomposition", "price_trend_by_commodity",
    "social_sentiment", "sentiment_topic_trend", "pipeline_runs",
]

COLORS = {
    "psx": "#185FA5", "bsp": "#533AB7", "fx": "#0F6E56",
    "gdp": "#1D9E75", "cpi": "#BA7517", "inflation": "#E24B4A",
    "regional": "#2E8B57", "sentiment": "#9B59B6", "neutral": "#888780",
}

_LAYOUT_STYLE = {"backgroundColor": "transparent", "color": "inherit"}

# ---------------------------------------------------------------------------
# App initialisation
# ---------------------------------------------------------------------------

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.FLATLY],
    title="PH Dashboard — Explorer",
    suppress_callback_exceptions=True,
)
server = app.server   # expose for gunicorn if needed


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(cfg.DB_PATH), read_only=True)


def _query(sql: str) -> tuple[pd.DataFrame, str | None]:
    """Execute SQL. Returns (DataFrame, error_message).

    PATCH FINDING-001: nested try/finally guarantees con.close() is called
    even when con.execute() raises, preventing connection leaks under
    Dash's multi-threaded callback server.
    """
    try:
        con = _connect()
        try:
            df = con.execute(sql).df()
            return df, None
        finally:
            con.close()
    except Exception as exc:
        return pd.DataFrame(), str(exc)


def _list_views() -> list[str]:
    df, _ = _query("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'main'
        ORDER BY table_name
    """)
    return df["table_name"].tolist() if not df.empty else VIEWS


def _columns(view: str) -> list[str]:
    df, _ = _query(f"SELECT * FROM {view} LIMIT 0")
    return df.columns.tolist()


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

def _card(title: str, body: list) -> dbc.Card:
    return dbc.Card([
        dbc.CardHeader(html.Strong(title)),
        dbc.CardBody(body),
    ], className="mb-3 shadow-sm")


# ---------------------------------------------------------------------------
# App layout
# ---------------------------------------------------------------------------

app.layout = dbc.Container(fluid=True, children=[
    # Header
    dbc.Row(dbc.Col(html.Div([
        html.H3("🇵🇭 PH Economic Intelligence — Explorer", className="mb-0"),
        html.P("Power-user view · DuckDB direct · Arbitrary queries",
               className="text-muted mb-0 small"),
    ], className="py-3 border-bottom mb-3"))),

    dbc.Tabs(id="tabs", active_tab="tab-explorer", children=[

        # ── Tab 1: Explorer ──────────────────────────────────────────────────
        dbc.Tab(label="📊 Explorer", tab_id="tab-explorer", children=[
            dbc.Row([
                # Left controls
                dbc.Col(width=3, children=[
                    _card("Data source", [
                        dbc.Label("View / table"),
                        dcc.Dropdown(id="view-select",
                                     options=[{"label": v, "value": v} for v in VIEWS],
                                     value="psx_prices",
                                     clearable=False),
                        html.Div(id="schema-info", className="mt-2 small text-muted"),
                    ]),
                    _card("Date filter", [
                        dbc.Label("Date column"),
                        dcc.Dropdown(id="date-col-select", clearable=True,
                                     placeholder="Auto-detect…"),
                        dbc.Label("Date range", className="mt-2"),
                        dcc.DatePickerRange(
                            id="date-range",
                            start_date=(date.today() - timedelta(days=365)).isoformat(),
                            end_date=date.today().isoformat(),
                            display_format="YYYY-MM-DD",
                            className="w-100",
                        ),
                        dbc.Checkbox(id="ignore-date", label="Ignore date filter",
                                     value=False, className="mt-2"),
                    ]),
                    _card("Chart axes", [
                        dbc.Label("X axis"),
                        dcc.Dropdown(id="x-col", clearable=True, placeholder="Select column…"),
                        dbc.Label("Y axis", className="mt-2"),
                        dcc.Dropdown(id="y-col", clearable=True, placeholder="Select column…"),
                        dbc.Label("Color by", className="mt-2"),
                        dcc.Dropdown(id="color-col", clearable=True, placeholder="None"),
                        dbc.Label("Chart type", className="mt-2"),
                        dcc.Dropdown(
                            id="chart-type",
                            options=[
                                {"label": "Line", "value": "line"},
                                {"label": "Bar", "value": "bar"},
                                {"label": "Scatter", "value": "scatter"},
                                {"label": "Area", "value": "area"},
                                {"label": "Histogram", "value": "histogram"},
                                {"label": "Box", "value": "box"},
                            ],
                            value="line",
                            clearable=False,
                        ),
                        dbc.Button("▶ Render chart", id="render-btn",
                                   color="primary", className="mt-3 w-100"),
                    ]),
                    _card("Export", [
                        dbc.Button("⬇ Download CSV", id="dl-csv-btn",
                                   color="secondary", outline=True, className="w-100 mb-2"),
                        dcc.Download(id="dl-csv"),
                        dbc.Button("⬇ Download Parquet", id="dl-parquet-btn",
                                   color="secondary", outline=True, className="w-100"),
                        dcc.Download(id="dl-parquet"),
                    ]),
                ]),

                # Right: chart + data table
                dbc.Col(width=9, children=[
                    dcc.Loading(dcc.Graph(id="main-chart",
                                         style={"height": "420px"},
                                         config={"displayModeBar": True})),
                    html.Div(id="row-count", className="text-muted small mb-2"),
                    dcc.Loading(
                        dash_table.DataTable(
                            id="data-table",
                            page_size=25,
                            page_action="native",
                            sort_action="native",
                            filter_action="native",
                            style_table={"overflowX": "auto"},
                            style_header={"fontWeight": "bold", "backgroundColor": "#f8f9fa"},
                            style_cell={"fontSize": "12px", "padding": "4px 8px",
                                        "textAlign": "left", "maxWidth": "200px",
                                        "overflow": "hidden", "textOverflow": "ellipsis"},
                            style_data_conditional=[
                                {"if": {"row_index": "odd"},
                                 "backgroundColor": "#fafafa"},
                            ],
                            export_format="csv",
                        )
                    ),
                ]),
            ]),
        ]),

        # ── Tab 2: SQL Passthrough ────────────────────────────────────────────
        dbc.Tab(label="🔍 SQL Passthrough", tab_id="tab-sql", children=[
            dbc.Row([
                dbc.Col(width=12, children=[
                    _card("SQL Editor", [
                        html.P(
                            "Write any DuckDB-compatible SQL against the local database. "
                            "All registered views are available. Read-only connection.",
                            className="text-muted small mb-2",
                        ),
                        dcc.Textarea(
                            id="sql-input",
                            value=(
                                "-- Cross-domain query example:\n"
                                "SELECT\n"
                                "    DATE_TRUNC('month', p.date)::DATE  AS month,\n"
                                "    AVG(p.close)                       AS avg_psei,\n"
                                "    b.overnight_rp                     AS bsp_rate,\n"
                                "    c.inflation_pct\n"
                                "FROM psx_prices p\n"
                                "LEFT JOIN bsp_policy_rate b\n"
                                "    ON DATE_TRUNC('month', p.date) =\n"
                                "       DATE_TRUNC('month', b.decision_date)\n"
                                "LEFT JOIN cpi_trend c\n"
                                "    ON DATE_TRUNC('month', p.date) = c.period_date\n"
                                "WHERE p.ticker = 'PSEi.PS'\n"
                                "GROUP BY 1, b.overnight_rp, c.inflation_pct\n"
                                "ORDER BY 1\n"
                                "LIMIT 100"
                            ),
                            style={"width": "100%", "height": "220px",
                                   "fontFamily": "monospace", "fontSize": "13px",
                                   "padding": "8px", "border": "1px solid #dee2e6",
                                   "borderRadius": "4px"},
                        ),
                        dbc.Row([
                            dbc.Col(dbc.Button("▶ Execute", id="sql-run-btn",
                                               color="primary", className="mt-2"),
                                    width="auto"),
                            dbc.Col(dbc.Button("⬇ Download result CSV",
                                               id="sql-dl-btn", color="secondary",
                                               outline=True, className="mt-2 ms-2"),
                                    width="auto"),
                            dbc.Col(dcc.Download(id="sql-dl"), width="auto"),
                            dbc.Col(html.Div(id="sql-meta",
                                             className="mt-2 small text-muted align-self-center"),
                                    width="auto"),
                        ]),
                    ]),
                ]),
            ]),
            dbc.Row([
                dbc.Col(width=12, children=[
                    dcc.Loading(
                        html.Div(id="sql-output")   # table or error rendered here
                    ),
                ]),
            ]),
            dbc.Row([
                dbc.Col(width=4, children=[
                    _card("Available views", [
                        html.Ul([html.Li(v, className="small font-monospace")
                                 for v in VIEWS],
                                className="mb-0 ps-3"),
                    ]),
                ]),
                dbc.Col(width=8, children=[
                    _card("Quick-start queries", [
                        html.Pre(
                            "-- PSX × BSP cross-join (last 90 days)\n"
                            "SELECT * FROM psx_vs_bsp\n"
                            "WHERE date >= CURRENT_DATE - INTERVAL '90 days';\n\n"
                            "-- Gini by region, latest year\n"
                            "SELECT region, gini_coefficient, mean_income\n"
                            "FROM regional_inequality\n"
                            "ORDER BY gini_coefficient DESC;\n\n"
                            "-- Pipeline run history\n"
                            "SELECT pipeline, status, rows_affected, run_at\n"
                            "FROM pipeline_runs ORDER BY run_at DESC LIMIT 20;\n\n"
                            "-- FX volatility regimes\n"
                            "SELECT vol_regime, COUNT(*) AS days,\n"
                            "       ROUND(AVG(annualized_vol)::NUMERIC, 4) AS avg_vol\n"
                            "FROM fx_volatility GROUP BY 1 ORDER BY 2 DESC;",
                            style={"fontSize": "11px", "backgroundColor": "#f8f9fa",
                                   "padding": "10px", "borderRadius": "4px",
                                   "border": "1px solid #dee2e6"},
                        ),
                    ]),
                ]),
            ]),
        ]),
    ]),
])


# ---------------------------------------------------------------------------
# Callbacks — Explorer tab
# ---------------------------------------------------------------------------

@callback(
    Output("date-col-select", "options"),
    Output("date-col-select", "value"),
    Output("x-col", "options"),
    Output("x-col", "value"),
    Output("y-col", "options"),
    Output("y-col", "value"),
    Output("color-col", "options"),
    Output("schema-info", "children"),
    Input("view-select", "value"),
)
def update_columns(view: str):
    if not view:
        empty = []
        return empty, None, empty, None, empty, None, empty, ""
    cols = _columns(view)
    opts = [{"label": c, "value": c} for c in cols]
    # Auto-detect date column
    date_keywords = ("date", "time", "at", "period")
    date_col = next((c for c in cols if any(k in c.lower() for k in date_keywords)), None)
    # Auto-detect numeric Y
    df_sample, _ = _query(f"SELECT * FROM {view} LIMIT 5")
    num_cols = [c for c in cols if df_sample[c].dtype.kind in ("f", "i")] if not df_sample.empty else []
    y_col = num_cols[0] if num_cols else (cols[1] if len(cols) > 1 else None)
    x_col = date_col or (cols[0] if cols else None)
    none_opt = [{"label": "— none —", "value": ""}]
    info = f"{len(cols)} columns" if cols else "No columns found"
    return opts, date_col, opts, x_col, opts, y_col, none_opt + opts, info


@callback(
    Output("main-chart", "figure"),
    Output("data-table", "data"),
    Output("data-table", "columns"),
    Output("row-count", "children"),
    Input("render-btn", "n_clicks"),
    State("view-select", "value"),
    State("date-col-select", "value"),
    State("date-range", "start_date"),
    State("date-range", "end_date"),
    State("ignore-date", "value"),
    State("x-col", "value"),
    State("y-col", "value"),
    State("color-col", "value"),
    State("chart-type", "value"),
    prevent_initial_call=True,
)
def render_explorer(n, view, date_col, start, end, ignore_date,
                    x_col, y_col, color_col, chart_type):
    if not view or not x_col or not y_col:
        return go.Figure(), [], [], ""

    date_clause = ""
    if date_col and not ignore_date and start and end:
        date_clause = f"WHERE {date_col} BETWEEN '{start}' AND '{end}'"

    sql = f"SELECT * FROM {view} {date_clause} LIMIT 10000"
    df, err = _query(sql)

    if err:
        fig = go.Figure()
        fig.add_annotation(text=f"Error: {err}", x=0.5, y=0.5,
                           xref="paper", yref="paper", showarrow=False,
                           font=dict(color="red", size=13))
        return fig, [], [], ""

    if df.empty:
        return go.Figure(), [], [], "No rows returned."

    color_arg = color_col if color_col else None
    try:
        if chart_type == "line":
            fig = px.line(df, x=x_col, y=y_col, color=color_arg)
        elif chart_type == "bar":
            fig = px.bar(df, x=x_col, y=y_col, color=color_arg)
        elif chart_type == "scatter":
            fig = px.scatter(df, x=x_col, y=y_col, color=color_arg, trendline="ols")
        elif chart_type == "area":
            fig = px.area(df, x=x_col, y=y_col, color=color_arg)
        elif chart_type == "histogram":
            fig = px.histogram(df, x=x_col, color=color_arg)
        elif chart_type == "box":
            fig = px.box(df, x=color_arg or x_col, y=y_col)
        else:
            fig = px.line(df, x=x_col, y=y_col)
    except Exception as exc:
        fig = go.Figure()
        fig.add_annotation(text=f"Chart error: {exc}", x=0.5, y=0.5,
                           xref="paper", yref="paper", showarrow=False,
                           font=dict(color="red", size=12))

    fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=28, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )

    # DataTable
    tbl_cols = [{"name": c, "id": c} for c in df.columns]
    tbl_data = df.head(500).to_dict("records")
    row_info = f"{len(df):,} rows returned (table shows first 500)"
    return fig, tbl_data, tbl_cols, row_info


@callback(
    Output("dl-csv", "data"),
    Input("dl-csv-btn", "n_clicks"),
    State("view-select", "value"),
    State("date-col-select", "value"),
    State("date-range", "start_date"),
    State("date-range", "end_date"),
    State("ignore-date", "value"),
    prevent_initial_call=True,
)
def download_csv(n, view, date_col, start, end, ignore_date):
    if not view:
        return dash.no_update
    date_clause = ""
    if date_col and not ignore_date and start and end:
        date_clause = f"WHERE {date_col} BETWEEN '{start}' AND '{end}'"
    df, _ = _query(f"SELECT * FROM {view} {date_clause}")
    if df.empty:
        return dash.no_update
    return dcc.send_data_frame(df.to_csv, f"{view}.csv", index=False)


@callback(
    Output("dl-parquet", "data"),
    Input("dl-parquet-btn", "n_clicks"),
    State("view-select", "value"),
    State("date-col-select", "value"),
    State("date-range", "start_date"),
    State("date-range", "end_date"),
    State("ignore-date", "value"),
    prevent_initial_call=True,
)
def download_parquet(n, view, date_col, start, end, ignore_date):
    if not view:
        return dash.no_update
    date_clause = ""
    if date_col and not ignore_date and start and end:
        date_clause = f"WHERE {date_col} BETWEEN '{start}' AND '{end}'"
    df, _ = _query(f"SELECT * FROM {view} {date_clause}")
    if df.empty:
        return dash.no_update
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    buf.seek(0)
    return dcc.send_bytes(buf.read, f"{view}.parquet")


# ---------------------------------------------------------------------------
# Callbacks — SQL Passthrough tab
# ---------------------------------------------------------------------------

@callback(
    Output("sql-output", "children"),
    Output("sql-meta", "children"),
    Input("sql-run-btn", "n_clicks"),
    State("sql-input", "value"),
    prevent_initial_call=True,
)
def run_sql(n: int, sql: str):
    if not sql or not sql.strip():
        return html.P("Enter a SQL query above.", className="text-muted"), ""

    df, err = _query(sql.strip())

    if err:
        return (
            dbc.Alert([
                html.Strong("Query error:"),
                html.Pre(err, style={"fontSize": "12px", "marginTop": "8px", "marginBottom": 0}),
            ], color="danger", className="mt-3"),
            "",
        )

    if df.empty:
        return dbc.Alert("Query returned 0 rows.", color="info", className="mt-3"), "0 rows"

    meta = f"{len(df):,} rows × {len(df.columns)} columns"

    table = dash_table.DataTable(
        data=df.head(1000).to_dict("records"),
        columns=[{"name": c, "id": c} for c in df.columns],
        page_size=25,
        page_action="native",
        sort_action="native",
        filter_action="native",
        style_table={"overflowX": "auto", "marginTop": "12px"},
        style_header={"fontWeight": "bold", "backgroundColor": "#f8f9fa"},
        style_cell={"fontSize": "12px", "padding": "4px 8px",
                    "textAlign": "left", "maxWidth": "240px",
                    "overflow": "hidden", "textOverflow": "ellipsis"},
        style_data_conditional=[
            {"if": {"row_index": "odd"}, "backgroundColor": "#fafafa"},
        ],
        export_format="csv",
        id="sql-result-table",
    )
    note = html.P(f"Showing first 1,000 of {len(df):,} rows. "
                  "Use LIMIT in your query for large results.",
                  className="text-muted small mt-1") if len(df) > 1000 else None

    return html.Div([table] + ([note] if note else [])), meta


@callback(
    Output("sql-dl", "data"),
    Input("sql-dl-btn", "n_clicks"),
    State("sql-input", "value"),
    prevent_initial_call=True,
)
def download_sql_result(n: int, sql: str):
    if not sql:
        return dash.no_update
    df, _ = _query(sql.strip())
    if df.empty:
        return dash.no_update
    return dcc.send_data_frame(df.to_csv, "sql_result.csv", index=False)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=8050)
