"""
PH Dashboard — Streamlit app (Phase 9: full dashboard).

Pages:
  Status        — pipeline health + run log
  Markets       — PSX OHLCV, MA overlays, RSI, volume anomaly, sector heatmap
  Monetary Policy — BSP rate timeline, CPI lag correlation
  FX            — USD/PHP daily, cross rates, volatility bands, real rate
  Labor         — regional unemployment/underemployment map, LFS round delta
  Prices        — commodity retail prices, STL decomposition, fuel overlay
  Regional      — Gini choropleth, income quintile breakdown, Palma ratio
  Economy       — GDP, CPI, OFW remittances, economic dashboard
  Sentiment     — topic trend, sentiment vs PSX, topic heatmap
  Budget        — COA pipeline (Phase 11 stub)
  Cross-Analysis — user-selectable multi-domain overlay

Run:
    streamlit run apps/streamlit_app.py

To run scheduled pipeline jobs, start the scheduler in a separate terminal:
    python -m scheduler.main

"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config as cfg
from components.charts import (
    COLORS, area, bar, candlestick, dual_axis, line,
    ph_choropleth, scatter, sentiment_stack,
)
from components.maps import ph_region_bar
from components.tables import (
    bsp_table, download_csv, fx_table, pipeline_runs_table,
    prices_table, psx_table, regional_table,
)
from lib.db import get_read_conn

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="PH Economic Intelligence Dashboard",
    page_icon="🇵🇭",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# DB helper
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60)
def _q(sql: str) -> pd.DataFrame:
    try:
        with get_read_conn() as con:
            return con.execute(sql).df()
    except Exception as exc:
        return pd.DataFrame({"_error": [str(exc)]})


def _ok(df: pd.DataFrame) -> bool:
    return "_error" not in df.columns and not df.empty


def _err_or_empty(df: pd.DataFrame, label: str) -> bool:
    if "_error" in df.columns:
        st.error(f"{label}: {df['_error'].iloc[0]}")
        return True
    if df.empty:
        st.info(f"No data for {label}. Run the pipeline first.")
        return True
    return False


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

PAGES = [
    "📊 Status", "📈 Markets", "🏦 Monetary Policy", "💱 FX",
    "👷 Labor", "🛒 Prices", "🗺️ Regional", "📉 Economy",
    "💬 Sentiment", "🏛️ Budget", "🔀 Cross-Analysis",
]

with st.sidebar:
    st.image(
        "https://upload.wikimedia.org/wikipedia/commons/thumb/9/99/"
        "Flag_of_the_Philippines.svg/320px-Flag_of_the_Philippines.svg.png",
        width=56,
    )
    st.title("PH Dashboard")
    st.caption("Philippine Economic Intelligence")
    st.divider()
    page = st.radio("Navigate", PAGES, index=0, label_visibility="collapsed")
    st.divider()
    st.caption(f"DB: `{cfg.DB_PATH.name}`")
    # Scheduler status via heartbeat file — written by scheduler/main.py every 60s.
    import time as _time
    from pathlib import Path as _Path
    _hb = _Path("db/scheduler.heartbeat")
    if _hb.exists():
        age = _time.time() - float(_hb.read_text() or "0")
        scheduler_label = "⏱️ Scheduler: **active**" if age < 120 else "⏱️ Scheduler: **stale** (>2 min)"
    else:
        scheduler_label = "⏱️ Scheduler: off (run `python -m scheduler.main`)"
    st.caption(scheduler_label)
    if st.button("🔄 Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


# ---------------------------------------------------------------------------
# Page: Status
# ---------------------------------------------------------------------------

PIPELINES = ["psx", "bsp", "fx", "economic", "labor", "regional",
             "prices", "sentiment", "coa"]
_MIN_ROWS = {"psx": 1000, "bsp": 50, "fx": 500, "economic": 10,
             "labor": 0, "regional": 1, "prices": 100, "sentiment": 10, "coa": 0}


def _status_badge(status: str) -> str:
    return {"success": "✅", "error": "❌", "running": "🔄"}.get(status, "❓")


def page_status() -> None:
    st.header("Pipeline Status", divider="gray")
    runs = _q("""
        SELECT pipeline, status, rows_affected, error_msg, run_at
        FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY pipeline ORDER BY run_at DESC) rn
              FROM pipeline_runs)
        WHERE rn = 1 ORDER BY pipeline
    """)
    run_map = ({r["pipeline"]: r for _, r in runs.iterrows()} if _ok(runs) else {})

    rows = []
    for p in PIPELINES:
        if p in run_map:
            r = run_map[p]
            ts = r["run_at"]
            ts_str = ts.strftime("%Y-%m-%d %H:%M") if hasattr(ts, "strftime") else str(ts)[:16]
            s = r["status"]; n = int(r["rows_affected"] or 0); e = r["error_msg"] or ""
            mn = _MIN_ROWS.get(p, 1)
            health = ("✅ Healthy" if s == "success" and (mn == 0 or n >= mn) else
                      "⚠️ Empty (data gap)" if s == "success" and n == 0 and mn == 0 else
                      "⚠️ Low rows" if s == "success" else "❌ Error")
        else:
            ts_str = "—"; s = "never_run"; n = 0; e = ""; health = "⬜ Never run"
        rows.append({"Pipeline": p, "Health": health, "Status": _status_badge(s) + " " + s,
                     "Rows": f"{n:,}" if n else "—", "Last run": ts_str, "Error": e[:80]})

    df = pd.DataFrame(rows)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pipelines", len(PIPELINES))
    c2.metric("Healthy", sum(1 for r in rows if r["Health"].startswith("✅")))
    c3.metric("Never run", sum(1 for r in rows if "Never" in r["Health"]))
    c4.metric("Errors", sum(1 for r in rows if r["Health"].startswith("❌")))
    st.divider()
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.divider()
    st.subheader("Recent run log")
    log = _q("SELECT run_at, pipeline, status, rows_affected, error_msg "
             "FROM pipeline_runs ORDER BY run_at DESC LIMIT 20")
    if _ok(log):
        log["run_at"] = pd.to_datetime(log["run_at"]).dt.strftime("%Y-%m-%d %H:%M:%S")
        st.dataframe(**pipeline_runs_table(log))
    else:
        st.info("No runs recorded yet.")
    if cfg.DB_PATH.exists():
        st.caption(f"DB: `{cfg.DB_PATH}` — {cfg.DB_PATH.stat().st_size / 1_048_576:.1f} MB")


# ---------------------------------------------------------------------------
# Page: Markets
# ---------------------------------------------------------------------------

def page_markets() -> None:
    st.header("📈 Markets — PSX", divider="gray")
    with st.sidebar:
        tickers = _q("SELECT DISTINCT ticker FROM psx_prices ORDER BY ticker")
        ticker_list = tickers["ticker"].tolist() if _ok(tickers) else ["PSEi.PS"]
        sel_ticker = st.selectbox("Ticker", ticker_list, index=0)
        days = st.slider("Look-back (days)", 90, 1825, 365)

    cutoff = (date.today() - timedelta(days=days)).isoformat()
    df = _q(f"""
        SELECT date, open, high, low, close, volume, ma_20, ma_50, rsi_14, volume_zscore
        FROM psx_prices
        WHERE ticker = '{sel_ticker}' AND date >= '{cutoff}'
        ORDER BY date
    """)
    if _err_or_empty(df, f"PSX {sel_ticker}"):
        return

    latest = df.iloc[-1]
    prev   = df.iloc[-2] if len(df) > 1 else latest
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Close", f"₱{latest['close']:.2f}",
              delta=f"{(latest['close'] - prev['close']):.2f}")
    c2.metric("Volume", f"{int(latest['volume']):,}")
    c3.metric("RSI-14", f"{latest['rsi_14']:.1f}" if pd.notna(latest.get("rsi_14")) else "—")
    c4.metric("Vol Z-score", f"{latest['volume_zscore']:.2f}"
              if pd.notna(latest.get("volume_zscore")) else "—")
    st.divider()

    tab1, tab2, tab3, tab4 = st.tabs(["Candlestick + MA", "RSI", "Volume", "Data"])
    with tab1:
        fig = candlestick(df, date_col="date", title=f"{sel_ticker} OHLCV")
        for ma_col, ma_color, ma_name in [("ma_20", COLORS["fx"], "MA-20"),
                                           ("ma_50", COLORS["cpi"], "MA-50")]:
            if ma_col in df.columns and df[ma_col].notna().any():
                fig.add_trace(go.Scatter(x=df["date"], y=df[ma_col],
                                         mode="lines", name=ma_name,
                                         line=dict(width=1.5,
                                                   color=ma_color if ma_col == "ma_20"
                                                   else COLORS["cpi"])))
        st.plotly_chart(fig, use_container_width=True)

    with tab2:
        rsi_df = df.dropna(subset=["rsi_14"])
        if not rsi_df.empty:
            fig2 = line(rsi_df, x="date", y="rsi_14", color="bsp", title="RSI-14")
            fig2.add_hline(y=70, line_dash="dot", line_color=COLORS["inflation"])
            fig2.add_hline(y=30, line_dash="dot", line_color=COLORS["gdp"])
            st.plotly_chart(fig2, use_container_width=True)
            st.caption("RSI > 70: overbought  |  RSI < 30: oversold")
        else:
            st.info("RSI data not available.")

    with tab3:
        fig3 = bar(df, x="date", y="volume", color="psx", title="Daily Volume")
        if "volume_zscore" in df.columns:
            anomalies = df[df["volume_zscore"].abs() > 2]
            if not anomalies.empty:
                fig3.add_trace(go.Scatter(x=anomalies["date"], y=anomalies["volume"],
                                          mode="markers", marker=dict(color=COLORS["inflation"],
                                          size=8, symbol="circle-open"), name="Anomaly (|z|>2)"))
        st.plotly_chart(fig3, use_container_width=True)

    with tab4:
        st.dataframe(**psx_table(df.tail(60)))
        download_csv(df, f"psx_{sel_ticker}_{days}d.csv")


# ---------------------------------------------------------------------------
# Page: Monetary Policy
# ---------------------------------------------------------------------------

def page_monetary() -> None:
    st.header("🏦 Monetary Policy — BSP", divider="gray")
    bsp = _q("SELECT * FROM bsp_policy_rate ORDER BY decision_date")
    cpi = _q("SELECT period_date, cpi_index, inflation_pct FROM cpi_trend "
             "WHERE inflation_pct IS NOT NULL ORDER BY period_date")
    if _err_or_empty(bsp, "BSP policy rate"):
        return

    latest_bsp = bsp.iloc[-1]
    c1, c2, c3 = st.columns(3)
    c1.metric("Current Overnight RP",
              f"{latest_bsp['overnight_rp']:.2f}%" if pd.notna(latest_bsp.get("overnight_rp")) else "—")
    c2.metric("Direction", str(latest_bsp.get("direction", "—")))
    c3.metric("Last decision", str(latest_bsp["decision_date"])[:10])
    st.divider()

    tab1, tab2, tab3 = st.tabs(["Rate timeline", "Rate vs CPI", "Data"])
    with tab1:
        fig = line(bsp, x="decision_date", y="overnight_rp", color="bsp",
                   title="BSP Overnight RP Rate (%)", yaxis_suffix="%")
        directions = bsp[bsp["direction"] == "hike"]
        if not directions.empty:
            fig.add_trace(go.Scatter(x=directions["decision_date"], y=directions["overnight_rp"],
                                     mode="markers", marker=dict(color=COLORS["inflation"],
                                     size=9, symbol="triangle-up"), name="Hike"))
        cuts = bsp[bsp["direction"] == "cut"]
        if not cuts.empty:
            fig.add_trace(go.Scatter(x=cuts["decision_date"], y=cuts["overnight_rp"],
                                     mode="markers", marker=dict(color=COLORS["gdp"],
                                     size=9, symbol="triangle-down"), name="Cut"))
        st.plotly_chart(fig, use_container_width=True)

    with tab2:
        if _ok(cpi):
            bsp_m = bsp.copy()
            bsp_m["month"] = pd.to_datetime(bsp_m["decision_date"]).dt.to_period("M").dt.to_timestamp()
            cpi_m = cpi.copy()
            cpi_m["month"] = pd.to_datetime(cpi_m["period_date"]).dt.to_period("M").dt.to_timestamp()
            merged = pd.merge(bsp_m[["month", "overnight_rp"]], cpi_m[["month", "inflation_pct"]],
                              on="month", how="inner")
            if not merged.empty:
                fig2 = dual_axis(merged, x="month", y1="overnight_rp", y2="inflation_pct",
                                 color1="bsp", color2="inflation", title="Policy Rate vs Inflation",
                                 y1_suffix="%", y2_suffix="%",
                                 labels={"overnight_rp": "Overnight RP (%)",
                                         "inflation_pct": "CPI YoY (%)"})
                st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("CPI data unavailable — run the economic pipeline first.")

    with tab3:
        st.dataframe(**bsp_table(bsp.sort_values("decision_date", ascending=False).head(30)))
        download_csv(bsp, "bsp_policy_rate.csv")


# ---------------------------------------------------------------------------
# Page: FX
# ---------------------------------------------------------------------------

def page_fx() -> None:
    st.header("💱 FX Rates", divider="gray")
    with st.sidebar:
        fx_days = st.slider("Look-back (days)", 90, 1825, 365, key="fx_days")

    cutoff = (date.today() - timedelta(days=fx_days)).isoformat()
    usdphp = _q(f"""
        SELECT rate_date, rate FROM stg_fx_rates
        WHERE rate_date >= '{cutoff}'
        ORDER BY rate_date
    """)
    vol = _q(f"""
        SELECT rate_date, rate, vol_30d, vol_7d, annualized_vol, vol_regime
        FROM fx_volatility
        WHERE rate_date >= '{cutoff}'
        ORDER BY rate_date
    """)
    cross = _q("""
        SELECT rate_date, base_currency, php_rate FROM fx_rates
        WHERE currency_pair LIKE '%/PHP' AND currency_pair != 'USD/PHP'
          AND rate_date = (SELECT MAX(rate_date) FROM fx_rates)
        ORDER BY base_currency
    """)

    if _err_or_empty(usdphp, "FX USD/PHP"):
        return

    latest_rate = usdphp.iloc[-1]
    prev_rate   = usdphp.iloc[-2] if len(usdphp) > 1 else latest_rate
    c1, c2, c3 = st.columns(3)
    c1.metric("USD/PHP", f"₱{latest_rate['rate']:.4f}",
              delta=f"{(latest_rate['rate'] - prev_rate['rate']):.4f}")
    if _ok(vol) and not vol.empty:
        lv = vol.iloc[-1]
        c2.metric("30d Volatility", f"{lv['vol_30d']:.4f}" if pd.notna(lv.get("vol_30d")) else "—")
        c3.metric("Vol Regime", str(lv.get("vol_regime", "—")).title())
    st.divider()

    tab1, tab2, tab3, tab4 = st.tabs(["USD/PHP", "Volatility", "Cross rates", "Data"])
    with tab1:
        fig = line(usdphp, x="rate_date", y="rate", color="fx",
                   title="USD/PHP Daily Rate (forward-filled)")
        st.plotly_chart(fig, use_container_width=True)

    with tab2:
        if _ok(vol) and "vol_30d" in vol.columns:
            fig2 = dual_axis(vol.dropna(subset=["vol_30d"]),
                             x="rate_date", y1="rate", y2="vol_30d",
                             color1="fx", color2="cpi",
                             title="USD/PHP Rate vs 30d Volatility",
                             labels={"rate": "USD/PHP", "vol_30d": "30d Std Dev"})
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("Volatility data not available.")

    with tab3:
        if _ok(cross) and not cross.empty:
            fig3 = ph_region_bar(cross, region_col="base_currency", value_col="php_rate",
                                 title="Current Cross Rates vs PHP", color="fx")
            st.plotly_chart(fig3, use_container_width=True)
        else:
            st.info("Cross rate data not available.")

    with tab4:
        st.dataframe(**fx_table(usdphp.tail(60)))
        download_csv(usdphp, f"fx_usdphp_{fx_days}d.csv")


# ---------------------------------------------------------------------------
# Page: Labor
# ---------------------------------------------------------------------------

def page_labor() -> None:
    st.header("👷 Labor Market", divider="gray")
    df = _q("SELECT * FROM labor_market ORDER BY survey_round, region")
    if df.empty or ("unemployment_rate" not in df.columns):
        st.info(
            "No labor market data loaded.\n\n"
            "To enable: download PSA LFS CSV, set `cfg.LABOR_LFS_CSV`, "
            "and run `python -m pipelines.labor.run`."
        )
        return
    if "_error" in df.columns:
        st.error(df["_error"].iloc[0])
        return

    rounds = sorted(df["survey_round"].dropna().unique())
    sel_round = st.selectbox("Survey round", rounds, index=len(rounds) - 1)
    df_r = df[df["survey_round"] == sel_round]

    c1, c2, c3 = st.columns(3)
    c1.metric("Avg unemployment", f"{df_r['unemployment_rate'].mean():.1f}%")
    c2.metric("Avg underemployment", f"{df_r['underemployment_rate'].mean():.1f}%"
              if "underemployment_rate" in df_r.columns else "—")
    c3.metric("Regions covered", df_r["region"].nunique())
    st.divider()

    tab1, tab2 = st.tabs(["Regional map", "Data"])
    with tab1:
        fig = ph_region_bar(df_r, region_col="region", value_col="unemployment_rate",
                            title=f"Unemployment Rate by Region — {sel_round}",
                            color="labor", value_suffix="%")
        st.plotly_chart(fig, use_container_width=True)
        if "underemployment_rate" in df_r.columns:
            fig2 = ph_region_bar(df_r, region_col="region", value_col="underemployment_rate",
                                 title=f"Underemployment Rate — {sel_round}",
                                 color="labor", value_suffix="%")
            st.plotly_chart(fig2, use_container_width=True)
    with tab2:
        st.dataframe(df_r, use_container_width=True, hide_index=True)
        download_csv(df_r, f"labor_{sel_round}.csv")


# ---------------------------------------------------------------------------
# Page: Prices
# ---------------------------------------------------------------------------

def page_prices() -> None:
    st.header("🛒 Prices", divider="gray")
    commodities = _q("SELECT DISTINCT commodity_slug, commodity FROM commodity_prices ORDER BY commodity")
    if not _ok(commodities):
        st.info("No price data. Run `python -m pipelines.prices.run`.")
        return

    with st.sidebar:
        slug_map = dict(zip(commodities["commodity"].tolist(), commodities["commodity_slug"].tolist()))
        sel_commodity = st.selectbox("Commodity", list(slug_map.keys()), key="prices_commodity")
        sel_slug = slug_map[sel_commodity]
        price_days = st.slider("Look-back (days)", 180, 3650, 1095, key="price_days")

    cutoff = (date.today() - timedelta(days=price_days)).isoformat()
    trend = _q(f"""
        SELECT month, avg_price, yoy_change_pct, cumulative_change_pct
        FROM price_trend_by_commodity
        WHERE commodity_slug = '{sel_slug}' AND month >= '{cutoff}'
        ORDER BY month
    """)
    decomp = _q(f"""
        SELECT period, observed, trend AS trend_val, seasonal, residual
        FROM food_price_decomposition
        WHERE commodity_slug = '{sel_slug}'
        ORDER BY period
    """)
    fuel = _q(f"""
        SELECT price_date, fuel_type, price_php FROM commodity_prices
        WHERE commodity_slug IN ('gasoline','diesel','lpg') AND price_date >= '{cutoff}'
        ORDER BY price_date, fuel_type
    """)

    if _err_or_empty(trend, f"{sel_commodity} trend"):
        return

    latest_p = trend.iloc[-1]
    c1, c2, c3 = st.columns(3)
    c1.metric("Latest avg price", f"₱{latest_p['avg_price']:.2f}")
    c2.metric("YoY change", f"{latest_p['yoy_change_pct']:+.1f}%"
              if pd.notna(latest_p.get("yoy_change_pct")) else "—")
    c3.metric("Cumulative change", f"{latest_p['cumulative_change_pct']:+.1f}%"
              if pd.notna(latest_p.get("cumulative_change_pct")) else "—")
    st.divider()

    tab1, tab2, tab3, tab4 = st.tabs(["Price trend", "STL decomposition", "Fuel", "Data"])
    with tab1:
        fig = area(trend, x="month", y="avg_price", color="prices",
                   title=f"{sel_commodity} — Monthly Average Retail Price (₱/kg)")
        st.plotly_chart(fig, use_container_width=True)
        if "yoy_change_pct" in trend.columns:
            fig2 = bar(trend.dropna(subset=["yoy_change_pct"]), x="month",
                       y="yoy_change_pct", title="Year-on-Year Price Change (%)",
                       yaxis_suffix="%", color_by_sign=True)
            st.plotly_chart(fig2, use_container_width=True)

    with tab2:
        if _ok(decomp) and not decomp.empty:
            for comp, color_key, title_str in [
                ("observed",  "prices",   "Observed"),
                ("trend_val", "cpi",      "Trend"),
                ("seasonal",  "fx",       "Seasonal"),
                ("residual",  "neutral",  "Residual"),
            ]:
                if comp in decomp.columns:
                    fig = line(decomp, x="period", y=comp, color=color_key,
                               title=f"STL — {title_str}")
                    if comp == "residual":
                        fig.add_hline(y=0, line_dash="dot", line_color=COLORS["neutral"])
                    st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("STL decomposition not available for this commodity "
                    "(requires ≥24 monthly observations).")

    with tab3:
        if _ok(fuel) and not fuel.empty:
            for ftype in ["gasoline", "diesel", "lpg"]:
                f = fuel[fuel["fuel_type"] == ftype]
                if not f.empty:
                    fig = line(f, x="price_date", y="price_php", color="fuel",
                               title=f"{ftype.title()} — Weekly Pump Price (₱/L)")
                    st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Fuel price data not available.")

    with tab4:
        st.dataframe(**prices_table(trend))
        download_csv(trend, f"prices_{sel_slug}_{price_days}d.csv")


# ---------------------------------------------------------------------------
# Page: Regional
# ---------------------------------------------------------------------------

def page_regional() -> None:
    st.header("🗺️ Regional Inequality", divider="gray")
    df = _q("SELECT * FROM regional_inequality ORDER BY survey_year, region")
    if _err_or_empty(df, "regional_inequality"):
        return

    years = sorted(df["survey_year"].dropna().unique())
    sel_year = st.selectbox("Survey year", years, index=len(years) - 1)
    df_y = df[df["survey_year"] == sel_year]

    c1, c2, c3 = st.columns(3)
    c1.metric("National avg Gini", f"{df_y['gini_coefficient'].mean():.4f}"
              if not df_y.empty else "—")
    c2.metric("Highest Gini", f"{df_y['gini_coefficient'].max():.4f} "
              f"({df_y.loc[df_y['gini_coefficient'].idxmax(), 'region']})"
              if not df_y.empty else "—")
    c3.metric("Regions", df_y["region"].nunique())
    st.divider()

    tab1, tab2, tab3, tab4 = st.tabs(["Gini", "Income quintiles", "Mean income", "Data"])
    with tab1:
        fig = ph_region_bar(df_y, region_col="region", value_col="gini_coefficient",
                            title=f"Gini Coefficient by Region — {sel_year}",
                            color="regional")
        st.plotly_chart(fig, use_container_width=True)

    with tab2:
        q_cols = ["income_share_q1", "income_share_q2", "income_share_q3",
                  "income_share_q4", "income_share_q5"]
        available_q = [c for c in q_cols if c in df_y.columns]
        if available_q:
            df_q = df_y[["region"] + available_q].melt(
                id_vars="region", var_name="quintile", value_name="share")
            df_q["quintile"] = df_q["quintile"].str.replace("income_share_", "").str.upper()
            import plotly.express as px
            fig2 = px.bar(df_q, x="region", y="share", color="quintile",
                          barmode="stack", title=f"Income Quintile Shares — {sel_year}",
                          color_discrete_sequence=[
                              COLORS["gdp"], COLORS["fx"], COLORS["bsp"],
                              COLORS["cpi"], COLORS["inflation"]])
            fig2.update_layout(xaxis_tickangle=-45,
                               plot_bgcolor="rgba(0,0,0,0)",
                               paper_bgcolor="rgba(0,0,0,0)",
                               margin=dict(l=0, r=0, t=28, b=0))
            st.plotly_chart(fig2, use_container_width=True)

    with tab3:
        if "mean_income" in df_y.columns:
            fig3 = ph_region_bar(df_y, region_col="region", value_col="mean_income",
                                 title=f"Mean Family Income (₱/yr) — {sel_year}",
                                 color="fx")
            st.plotly_chart(fig3, use_container_width=True)
        else:
            st.info("Mean income column not available.")

    with tab4:
        st.dataframe(**regional_table(df_y))
        download_csv(df_y, f"regional_{sel_year}.csv")


# ---------------------------------------------------------------------------
# Page: Economy
# ---------------------------------------------------------------------------

def page_economy() -> None:
    st.header("📉 Economy", divider="gray")
    with st.sidebar:
        year_min = st.slider("Start year", 1990, 2020, 2000, key="econ_year_min")
        year_max = st.slider("End year",   2001, 2025, 2024, key="econ_year_max")

    dash = _q(f"SELECT * FROM economic_dashboard WHERE period_year BETWEEN {year_min} AND {year_max} ORDER BY period_year")
    gdp  = _q(f"SELECT * FROM gdp_tracker WHERE period_year BETWEEN {year_min} AND {year_max} ORDER BY period_year")
    cpi  = _q(f"SELECT * FROM cpi_trend WHERE period_year BETWEEN {year_min} AND {year_max} ORDER BY period_date")
    remit= _q(f"SELECT * FROM remittance_trend WHERE period_year BETWEEN {year_min} AND {year_max} ORDER BY period_year")

    if _err_or_empty(dash, "economic_dashboard"):
        return

    lt = dash.iloc[-1]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("GDP", f"${lt.get('gdp_usd_bn', 0):.1f}B" if pd.notna(lt.get("gdp_usd_bn")) else "—",
              delta=f"{lt['gdp_growth_pct']:+.1f}%" if pd.notna(lt.get("gdp_growth_pct")) else None)
    c2.metric("Inflation (avg)", f"{lt.get('avg_inflation_pct', 0):.1f}%"
              if pd.notna(lt.get("avg_inflation_pct")) else "—")
    c3.metric("OFW Remittances", f"${lt.get('remittance_usd_bn', 0):.2f}B"
              if pd.notna(lt.get("remittance_usd_bn")) else "—")
    c4.metric("Remit/GDP", f"{lt.get('remit_to_gdp_pct_computed', 0):.1f}%"
              if pd.notna(lt.get("remit_to_gdp_pct_computed")) else "—")
    st.divider()

    tab_gdp, tab_cpi, tab_remit, tab_dash = st.tabs(["GDP", "CPI & Inflation", "Remittances", "Dashboard"])
    with tab_gdp:
        if _ok(gdp):
            col_a, col_b = st.columns(2)
            with col_a:
                st.plotly_chart(bar(gdp, x="period_year", y="gdp_usd_bn", color="gdp",
                                    title="GDP (USD Billions)"), use_container_width=True)
            with col_b:
                st.plotly_chart(line(gdp.dropna(subset=["gdp_growth_pct"]),
                                     x="period_year", y="gdp_growth_pct", color="gdp",
                                     title="GDP Growth Rate (%)", yaxis_suffix="%", zero_line=True),
                                use_container_width=True)
            st.plotly_chart(area(gdp, x="period_year", y="gdp_per_capita_usd",
                                 color="gdp", title="GDP per Capita (USD)"), use_container_width=True)

    with tab_cpi:
        if _ok(cpi):
            col_a, col_b = st.columns(2)
            with col_a:
                st.plotly_chart(line(cpi.dropna(subset=["cpi_index"]),
                                     x="period_date", y="cpi_index", color="cpi",
                                     title="CPI Index (2018=100)"), use_container_width=True)
            with col_b:
                st.plotly_chart(bar(cpi.dropna(subset=["inflation_pct"]),
                                    x="period_date", y="inflation_pct",
                                    title="Inflation Rate (% YoY)", yaxis_suffix="%",
                                    color_by_sign=True), use_container_width=True)

    with tab_remit:
        if _ok(remit):
            col_a, col_b = st.columns(2)
            with col_a:
                st.plotly_chart(bar(remit, x="period_year", y="remittance_usd_bn",
                                    color="remittance", title="OFW Remittances (USD Billions)"),
                                use_container_width=True)
            with col_b:
                st.plotly_chart(line(remit.dropna(subset=["remittance_yoy_pct"]),
                                     x="period_year", y="remittance_yoy_pct",
                                     color="remittance", title="Remittance YoY Growth (%)",
                                     yaxis_suffix="%", zero_line=True), use_container_width=True)

    with tab_dash:
        if _ok(dash):
            st.dataframe(dash, use_container_width=True, hide_index=True)
            download_csv(dash, f"economic_dashboard_{year_min}_{year_max}.csv")


# ---------------------------------------------------------------------------
# Page: Sentiment
# ---------------------------------------------------------------------------

def page_sentiment() -> None:
    st.header("💬 Sentiment", divider="gray")
    with st.sidebar:
        sent_days = st.slider("Look-back (days)", 7, 90, 30, key="sent_days")

    cutoff = (date.today() - timedelta(days=sent_days)).isoformat()
    df = _q(f"""
        SELECT scored_at, topic, sentiment_score, volume, source_platform, sentiment_label
        FROM social_sentiment WHERE scored_at >= '{cutoff}'
        ORDER BY scored_at
    """)
    topic_trend = _q(f"""
        SELECT obs_date, topic, avg_sentiment, total_volume
        FROM sentiment_topic_trend WHERE obs_date >= '{cutoff}'
        ORDER BY obs_date, topic
    """)

    if _err_or_empty(df, "social_sentiment"):
        return

    synthetic = "SYNTHETIC_FALLBACK" in df["source_platform"].unique()
    if synthetic:
        st.info("ℹ️ Displaying synthetic fallback data. "
                "Set Reddit credentials to enable live sentiment.")

    c1, c2, c3 = st.columns(3)
    c1.metric("Topics tracked", df["topic"].nunique())
    c2.metric("Total posts", f"{df['volume'].sum():,.0f}")
    c3.metric("Overall sentiment", f"{df['sentiment_score'].mean():+.3f}")
    st.divider()

    tab1, tab2, tab3 = st.tabs(["Topic trend", "Sentiment vs PSX", "Data"])
    with tab1:
        if _ok(topic_trend):
            topics = sorted(topic_trend["topic"].unique())
            sel_topics = st.multiselect("Topics", topics, default=topics[:3], key="sent_topics")
            filt = topic_trend[topic_trend["topic"].isin(sel_topics)] if sel_topics else topic_trend
            import plotly.express as px
            fig = px.line(filt, x="obs_date", y="avg_sentiment", color="topic",
                          title="Daily Average Sentiment by Topic")
            fig.add_hline(y=0, line_dash="dot", line_color=COLORS["neutral"])
            fig.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                               margin=dict(l=0, r=0, t=28, b=0))
            st.plotly_chart(fig, use_container_width=True)

    with tab2:
        psx_vs = _q(f"""
            SELECT obs_date, overall_sentiment, psei_close, rolling_30d_correlation
            FROM sentiment_vs_psx WHERE obs_date >= '{cutoff}'
            ORDER BY obs_date
        """)
        if _ok(psx_vs) and "psei_close" in psx_vs.columns and psx_vs["psei_close"].notna().any():
            fig2 = dual_axis(psx_vs.dropna(subset=["psei_close"]),
                             x="obs_date", y1="overall_sentiment", y2="psei_close",
                             color1="sentiment", color2="psx",
                             title="Sentiment vs PSEi Close",
                             labels={"overall_sentiment": "Sentiment", "psei_close": "PSEi Close"})
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("PSX data required for sentiment correlation. "
                    "Run `python -m pipelines.psx.run` first.")

    with tab3:
        st.dataframe(df.head(200), use_container_width=True, hide_index=True)
        download_csv(df, f"sentiment_{sent_days}d.csv")


# ---------------------------------------------------------------------------
# Page: Budget (Phase 11 stub)
# ---------------------------------------------------------------------------

def page_budget() -> None:
    st.header("🏛️ Budget — COA", divider="gray")
    st.info(
        "**COA Budget Utilization** — coming in Phase 11.\n\n"
        "The COA pipeline ingests PDF annual audit reports, normalizes agency "
        "disbursement rates across years, and flags LGU outliers.\n\n"
        "Run `python -m pipelines.coa.run` once Phase 11 is built."
    )
    coa = _q("SELECT * FROM coa_budget_utilization LIMIT 5")
    if _ok(coa):
        st.caption("Preview — `coa_budget_utilization`:")
        st.dataframe(coa, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Page: Cross-Analysis
# ---------------------------------------------------------------------------

def page_cross() -> None:
    st.header("🔀 Cross-Analysis", divider="gray")
    st.caption("Select two metrics from different domains to overlay on a dual-axis chart.")

    METRIC_QUERIES = {
        "PSX close (PSEi)":            ("psx_prices",      "date",        "close",               "psx"),
        "BSP overnight RP":            ("bsp_policy_rate", "decision_date","overnight_rp",        "bsp"),
        "USD/PHP rate":                ("stg_fx_rates",    "rate_date",    "rate",                "fx"),
        "CPI index":                   ("cpi_trend",       "period_date",  "cpi_index",           "cpi"),
        "Inflation % YoY":             ("cpi_trend",       "period_date",  "inflation_pct",       "inflation"),
        "GDP (USD Bn)":                ("gdp_tracker",     "period_date",  "gdp_usd_bn",          "gdp"),
        "OFW remittances (USD Bn)":    ("remittance_trend","period_date",  "remittance_usd_bn",   "remittance"),
        "Rice retail price":           ("commodity_prices","price_date",   "retail_price_php",    "prices"),
        "Overall sentiment":           ("social_sentiment","scored_at",    "sentiment_score",     "sentiment"),
    }

    col_a, col_b = st.columns(2)
    with col_a:
        sel1 = st.selectbox("Series A", list(METRIC_QUERIES.keys()), index=0)
    with col_b:
        sel2 = st.selectbox("Series B", list(METRIC_QUERIES.keys()), index=2)

    cross_days = st.slider("Look-back (days)", 90, 1825, 730, key="cross_days")
    cutoff = (date.today() - timedelta(days=cross_days)).isoformat()

    def _load_series(name: str) -> pd.DataFrame:
        tbl, xcol, ycol, _ = METRIC_QUERIES[name]
        filter_clause = f"WHERE {xcol} >= '{cutoff}'" if xcol not in ("period_year",) else ""
        q = f"SELECT {xcol}, AVG({ycol}) AS val FROM {tbl} {filter_clause} GROUP BY {xcol} ORDER BY {xcol}"
        df = _q(q)
        if _ok(df):
            df.columns = ["x", "val"]
            return df
        return pd.DataFrame()

    df1 = _load_series(sel1)
    df2 = _load_series(sel2)

    if df1.empty or df2.empty:
        st.info("One or both series unavailable. Run the relevant pipelines first.")
        return

    merged = pd.merge_asof(
        df1.sort_values("x").rename(columns={"val": "y1"}),
        df2.sort_values("x").rename(columns={"val": "y2", "x": "x2"}),
        left_on="x", right_on="x2", direction="nearest",
    ).dropna(subset=["y1", "y2"])

    if merged.empty:
        st.info("No overlapping date range between the two series.")
        return

    _, color1, _ = list(METRIC_QUERIES[sel1])[1], METRIC_QUERIES[sel1][3], None
    _, color2, _ = list(METRIC_QUERIES[sel2])[1], METRIC_QUERIES[sel2][3], None

    fig = dual_axis(merged, x="x", y1="y1", y2="y2",
                    color1=METRIC_QUERIES[sel1][3],
                    color2=METRIC_QUERIES[sel2][3],
                    title=f"{sel1}  vs  {sel2}",
                    labels={"y1": sel1, "y2": sel2})
    st.plotly_chart(fig, use_container_width=True)

    if st.checkbox("Show scatter correlation"):
        fig2 = scatter(merged, x="y1", y="y2", title=f"Scatter: {sel1} vs {sel2}",
                       labels={"y1": sel1, "y2": sel2})
        st.plotly_chart(fig2, use_container_width=True)

    download_csv(merged[["x", "y1", "y2"]].rename(columns={"x": "date", "y1": sel1, "y2": sel2}),
                 "cross_analysis.csv")


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

_ROUTER = {
    "📊 Status":          page_status,
    "📈 Markets":         page_markets,
    "🏦 Monetary Policy": page_monetary,
    "💱 FX":              page_fx,
    "👷 Labor":           page_labor,
    "🛒 Prices":          page_prices,
    "🗺️ Regional":        page_regional,
    "📉 Economy":         page_economy,
    "💬 Sentiment":       page_sentiment,
    "🏛️ Budget":          page_budget,
    "🔀 Cross-Analysis":  page_cross,
}

_ROUTER[page]()
