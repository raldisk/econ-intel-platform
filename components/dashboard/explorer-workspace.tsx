"use client"

import { useState, useEffect, useCallback } from "react"
import { KPICard } from "./kpi-card"
import { PriceChart } from "./price-chart"
import { DataTable } from "./data-table"
import { ControlPanel } from "./control-panel"
import { PanelHeader, EmptyState } from "./ui-primitives"
import { api, type KPIStat, type ViewAxisHint, type PipelineStatus } from "@/lib/api"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ChartPoint {
  date: string
  value: number
}

interface ViewState {
  columns: string[]
  rows: Record<string, unknown>[]
  chartData: ChartPoint[]
  kpis: KPIStat[]
  truncated: boolean
  loading: boolean
  error: string | null
}

const EMPTY_STATE: ViewState = {
  columns: [],
  rows: [],
  chartData: [],
  kpis: [],
  truncated: false,
  loading: false,
  error: null,
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildChartData(
  rows: Record<string, unknown>[],
  dateCol: string,
  valueCol: string,
): ChartPoint[] {
  if (!rows.length) return []
  return rows
    .map((r) => {
      const date = r[dateCol]
      const value = r[valueCol]
      if (date == null || value == null) return null
      const num = Number(value)
      if (isNaN(num)) return null
      return { date: String(date), value: num }
    })
    .filter((x): x is ChartPoint => x !== null)
}

// ---------------------------------------------------------------------------
// Synthetic data banner
// ---------------------------------------------------------------------------

function SyntheticBanner({ pipeline }: { pipeline: string }) {
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium bg-yellow-50 border border-yellow-200 text-yellow-800 rounded-md mx-1.5 mb-1">
      <span>⚠</span>
      <span>
        <strong>{pipeline}</strong> pipeline is using <strong>simulated data</strong>.
        Configure the required credentials or data files to enable live data.
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

// View-to-pipeline map — used to look up synthetic status for the active view.
const VIEW_PIPELINE_MAP: Record<string, string> = {
  psx_prices: "psx",
  bsp_policy_rate: "bsp",
  psx_vs_bsp: "psx",
  fx_rates: "fx",
  stg_fx_rates: "fx",
  fx_volatility: "fx",
  cpi_vs_fx: "fx",
  real_exchange_rate: "fx",
  cpi_trend: "economic",
  gdp_tracker: "economic",
  remittance_trend: "economic",
  economic_dashboard: "economic",
  labor_market: "labor",
  regional_inequality: "regional",
  commodity_prices: "prices",
  food_price_decomposition: "prices",
  price_trend_by_commodity: "prices",
  social_sentiment: "sentiment",
  sentiment_topic_trend: "sentiment",
  coa_budget_utilization: "coa",
  coa_low_utilizers: "coa",
}

export function ExplorerWorkspace() {
  // ── Registry fetched from API — no hardcoded VIEWS array ─────────────────
  const [viewList, setViewList] = useState<string[]>([])
  const [axisHints, setAxisHints] = useState<Record<string, ViewAxisHint>>({})
  const [pipelineStatuses, setPipelineStatuses] = useState<Record<string, PipelineStatus>>({})
  const [registryLoaded, setRegistryLoaded] = useState(false)

  useEffect(() => {
    Promise.all([
      api.fetchViewsMeta().catch(() => null),
      api.fetchStatus().catch(() => null),
    ]).then(([meta, status]) => {
      if (meta) {
        setViewList(meta.views)
        setAxisHints(meta.hints)
      }
      if (status) {
        const map: Record<string, PipelineStatus> = {}
        for (const p of status.pipelines) map[p.pipeline] = p
        setPipelineStatuses(map)
      }
      setRegistryLoaded(true)
    })
  }, [])

  // ── Per-view state ────────────────────────────────────────────────────────
  const [selectedView, setSelectedView] = useState("psx_prices")
  const [chartType, setChartType] = useState<"line" | "area" | "bar">("area")
  const [state, setState] = useState<ViewState>(EMPTY_STATE)
  const [dateRange, setDateRange] = useState({ start: "", end: "" })

  const hint = axisHints[selectedView] ?? { date_col: "date", value_col: "value" }
  const [xColumn, setXColumn] = useState(hint.date_col)
  const [yColumn, setYColumn] = useState(hint.value_col)

  // Sync axis columns when hint changes (view switched, registry loaded)
  useEffect(() => {
    const h = axisHints[selectedView]
    if (h) {
      setXColumn(h.date_col)
      setYColumn(h.value_col)
    }
  }, [selectedView, axisHints])

  // ── Data loading ──────────────────────────────────────────────────────────
  const load = useCallback(
    async (view: string, dateCol: string, valueCol: string) => {
      setState((s) => ({ ...s, loading: true, error: null }))
      try {
        const [rowsRaw, kpiRes] = await Promise.all([
          api.fetchData(view),
          api.fetchKPI(view, valueCol),
        ])

        const safeRows = Array.isArray(rowsRaw) ? rowsRaw : []
        const columns = safeRows.length > 0 ? Object.keys(safeRows[0]) : []

        const safeDateCol = columns.includes(dateCol) ? dateCol : columns[0]
        const safeValueCol = columns.includes(valueCol)
          ? valueCol
          : columns.find((c) => c !== safeDateCol) ?? columns[1]

        setState({
          columns,
          rows: safeRows,
          chartData: buildChartData(safeRows, safeDateCol, safeValueCol),
          kpis: kpiRes?.stats ?? [],
          truncated: false,
          loading: false,
          error: null,
        })
      } catch (err) {
        setState((s) => ({
          ...s,
          loading: false,
          error: err instanceof Error ? err.message : "Failed to load data",
        }))
      }
    },
    [],
  )

  useEffect(() => {
    load(selectedView, xColumn, yColumn)
  }, [selectedView, xColumn, yColumn, load])

  const handleRender = useCallback(() => {
    load(selectedView, xColumn, yColumn)
  }, [load, selectedView, xColumn, yColumn])

  const handleExportCSV = useCallback(() => {
    if (!state.rows.length) return
    const cols = state.columns
    const header = cols.join(",")
    const body = state.rows
      .map((row) => cols.map((c) => JSON.stringify(row[c] ?? "")).join(","))
      .join("\n")
    const blob = new Blob([header + "\n" + body], { type: "text/csv" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `${selectedView}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }, [state.rows, state.columns, selectedView])

  const handleViewChange = (view: string) => {
    setSelectedView(view)
    // Axis columns update via the useEffect above on axisHints change
  }

  const tableColumns = state.columns.map((col) => ({
    key: col,
    label: col.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase()),
    align: typeof state.rows[0]?.[col] === "number" ? "right" : "left",
  }))

  // Synthetic disclosure — check if the active view's backing pipeline is synthetic
  const activePipeline = VIEW_PIPELINE_MAP[selectedView]
  const pipelineStatus = activePipeline ? pipelineStatuses[activePipeline] : undefined
  const isSynthetic = pipelineStatus?.synthetic ?? false

  return (
    <div className="flex h-full">
      <div className="hidden w-56 lg:block">
        <ControlPanel
          views={registryLoaded ? viewList : ["psx_prices"]}
          selectedView={selectedView}
          onViewChange={handleViewChange}
          columns={state.columns.length ? state.columns : [xColumn, yColumn]}
          xColumn={xColumn}
          yColumn={yColumn}
          onXColumnChange={setXColumn}
          onYColumnChange={setYColumn}
          chartType={chartType}
          onChartTypeChange={setChartType}
          dateRange={dateRange}
          onDateRangeChange={setDateRange}
          onRender={handleRender}
          onExportCSV={handleExportCSV}
        />
      </div>

      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Synthetic data disclosure banner */}
        {isSynthetic && activePipeline && (
          <SyntheticBanner pipeline={activePipeline} />
        )}

        {/* KPI */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-1 p-1.5 border-b">
          {state.kpis.map((kpi, i) => (
            <KPICard key={i} {...kpi} />
          ))}
        </div>

        {/* Chart */}
        <div className="p-1.5 border-b">
          {state.chartData.length > 0 ? (
            <PriceChart data={state.chartData} type={chartType} height={180} />
          ) : (
            <div className="text-center text-sm text-muted-foreground h-[200px] flex items-center justify-center">
              {state.loading ? "Loading…" : "No compatible data"}
            </div>
          )}
        </div>

        {/* Table */}
        <div className="flex-1 overflow-hidden p-1.5">
          {state.error ? (
            <EmptyState>{state.error}</EmptyState>
          ) : (
            <DataTable columns={tableColumns} data={state.rows} />
          )}
        </div>
      </div>
    </div>
  )
}
