/**
 * PH Dashboard API Client
 * Single source of truth for frontend → backend communication.
 */

const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ??
  "http://127.0.0.1:8000"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface KPIStat {
  title: string
  value: string
  raw: number | null
  change_pct: number | null
  trend: "up" | "down" | "neutral"
}

export interface KPIResponse {
  view: string
  stats: KPIStat[]
}

export interface ViewMeta {
  name: string
  columns?: string[]
}

/** Shape returned by GET /views/meta */
export interface ViewAxisHint {
  date_col: string
  value_col: string
}

export interface ViewsMetaResponse {
  views: string[]
  hints: Record<string, ViewAxisHint>
}

/** Shape returned by GET /status */
export interface PipelineStatus {
  pipeline: string
  last_run: string | null
  last_status: "success" | "error" | "never"
  synthetic: boolean
}

export interface StatusResponse {
  pipelines: PipelineStatus[]
}

export interface QueryResponse {
  rows: Record<string, unknown>[]
  columns: string[]
  execution_ms?: number
  truncated?: boolean
}

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

async function request<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${path}`)
  return res.json()
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

export const api = {
  health(): Promise<{ status: string }> {
    return request("/health")
  },

  async fetchData(view: string): Promise<Record<string, unknown>[]> {
    const data = await request<{ rows?: Record<string, unknown>[] } | Record<string, unknown>[]>(`/data?view=${view}`)
    if (Array.isArray(data)) return data
    if (Array.isArray((data as { rows?: unknown[] }).rows)) return (data as { rows: Record<string, unknown>[] }).rows
    return []
  },

  fetchKPI(view: string, valueCol?: string): Promise<KPIResponse> {
    const params = new URLSearchParams()
    if (valueCol) params.set("value_col", valueCol)
    const qs = params.toString() ? `?${params}` : ""
    return request(`/kpi/${view}${qs}`)
  },

  /** GET /views/meta — view list + axis hints. Replaces hardcoded VIEWS array. */
  fetchViewsMeta(): Promise<ViewsMetaResponse> {
    return request("/views/meta")
  },

  /** GET /status — per-pipeline synthetic data disclosure. */
  fetchStatus(): Promise<StatusResponse> {
    return request("/status")
  },

  listViews(): Promise<{ views: ViewMeta[] }> {
    return request("/views")
  },

  async runQuery(query: string, limit: number = 1000): Promise<QueryResponse> {
    const res = await fetch(`${BASE_URL}/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sql: query, limit }),
    })
    if (!res.ok) {
      const text = await res.text()
      throw new Error(text || "Query failed")
    }
    return res.json()
  },
}
