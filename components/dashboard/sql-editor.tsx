"use client"

import { useState } from "react"
import { Play, Download, AlertCircle, CheckCircle2, Copy } from "lucide-react"
import { Button } from "@/components/ui/button"
import { DataTable } from "./data-table"
import { PanelHeader, StatusBadge, EmptyState } from "./ui-primitives"
import { api } from "@/lib/api"

interface SQLEditorProps {
  availableViews?: string[]
  quickStartQueries?: { label: string; query: string }[]
}

const DEFAULT_QUERY = `-- Cross-domain query example:
SELECT
    DATE_TRUNC('month', p.date)::DATE  AS month,
    AVG(p.close)                       AS avg_psei,
    b.overnight_rp                     AS bsp_rate,
    c.inflation_pct
FROM psx_prices p
LEFT JOIN bsp_policy_rate b
    ON DATE_TRUNC('month', p.date) =
       DATE_TRUNC('month', b.decision_date)
LEFT JOIN cpi_trend c
    ON DATE_TRUNC('month', p.date) = c.period_date
WHERE p.ticker = 'PSEi.PS'
GROUP BY 1, b.overnight_rp, c.inflation_pct
ORDER BY 1
LIMIT 100`

export function SQLEditor({
  availableViews = [],
  quickStartQueries = [],
}: SQLEditorProps) {
  const [query, setQuery] = useState(DEFAULT_QUERY)
  const [results, setResults] = useState<Record<string, unknown>[] | null>(null)
  const [resultColumns, setResultColumns] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [isRunning, setIsRunning] = useState(false)
  const [executionTime, setExecutionTime] = useState<number | null>(null)
  const [truncated, setTruncated] = useState(false)

const handleRun = async () => {
  console.log("RUN CLICKED")

  if (!query.trim()) return

  setIsRunning(true)
  setError(null)
  setResults(null)

  try {
    const cleanedQuery = query.trim().replace(/;$/, "")

    const res = await api.runQuery(cleanedQuery, 1_000)


    console.log("API RESPONSE:", res)

    setResults(res.rows)
    setResultColumns(res.columns)
    setExecutionTime(res.execution_ms)
    setTruncated(res.truncated)
  } catch (err) {
    console.error("RUN ERROR:", err)

    setError(err instanceof Error ? err.message : "Query failed")
  } finally {
    setIsRunning(false)
  }
}


  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault()
      void handleRun()
    }
  }

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(query)
    } catch {
      setError("Failed to copy query")
    }
  }

  const handleDownload = () => {
    if (!results || !resultColumns.length) return

    const csv = [
      resultColumns.join(","),
      ...results.map((r) =>
        resultColumns.map((col) => JSON.stringify(r[col] ?? "")).join(","),
      ),
    ].join("\n")

    const blob = new Blob([csv], { type: "text/csv" })
    const url = URL.createObjectURL(blob)

    const a = document.createElement("a")
    a.href = url
    a.download = "query_results.csv"
    a.click()

    URL.revokeObjectURL(url)
  }

  const columns = resultColumns.map((key) => ({
    key,
    label: key,
    align:
      results && typeof results[0]?.[key] === "number"
        ? ("right" as const)
        : ("left" as const),
  }))

  return (
    <div className="flex h-full flex-col lg:flex-row">
      <div className="flex flex-1 flex-col overflow-hidden">
        <PanelHeader
          actions={
            <>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleCopy}
                className="h-5 px-1.5 text-[10px] text-muted-foreground hover:text-foreground"
              >
                <Copy className="mr-1 h-3 w-3" />
                Copy
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={handleDownload}
                disabled={!results}
                className="h-5 px-1.5 text-[10px]"
              >
                <Download className="mr-1 h-3 w-3" />
                CSV
              </Button>
              <Button
                size="sm"
                onClick={() => void handleRun()}
                disabled={isRunning}
                className="h-5 px-1.5 text-[10px]"
                title="Run (Ctrl+Enter)"
              >
                <Play className="mr-1 h-3 w-3" />
                {isRunning ? "Running…" : "Run"}
              </Button>
            </>
          }
        >
          SQL Editor
        </PanelHeader>

        <div className="flex-shrink-0 border-b border-border">
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            className="h-32 w-full resize-none bg-muted px-3 py-2 font-mono text-[11px] leading-relaxed text-foreground focus:outline-none"
            spellCheck={false}
            placeholder="Enter a SELECT statement… (Ctrl+Enter to run)"
          />
        </div>

        <div className="flex h-6 items-center border-b border-border bg-card px-3 text-[10px]">
          {error ? (
            <div className="flex items-center gap-1 text-negative">
              <AlertCircle className="h-3 w-3 flex-shrink-0" />
              <span className="truncate">{error}</span>
            </div>
          ) : results ? (
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1 text-positive">
                <CheckCircle2 className="h-3 w-3" />
                <span>
                  {results.length.toLocaleString()} rows
                  {executionTime != null && ` in ${executionTime.toFixed(0)}ms`}
                </span>
              </div>
              {truncated && (
                <StatusBadge variant="warning">truncated at 1,000</StatusBadge>
              )}
            </div>
          ) : (
            <span className="text-muted-foreground">
              Ready — Ctrl+Enter to run
            </span>
          )}
        </div>

        <div className="flex-1 overflow-auto bg-background p-2">
          {results ? (
            <DataTable
              columns={columns}
              data={results}
              maxHeight="calc(100vh - 280px)"
            />
          ) : (
            <EmptyState>Run a query to see results</EmptyState>
          )}
        </div>
      </div>

      <div className="flex w-full flex-col border-t border-border lg:w-48 lg:border-l lg:border-t-0">
        <div className="border-b border-border bg-card">
          <PanelHeader>Views</PanelHeader>
          <ul className="max-h-32 space-y-0.5 overflow-y-auto p-1.5">
            {availableViews.map((view) => (
              <li
                key={view}
                onClick={() => setQuery(`SELECT * FROM ${view} LIMIT 100`)}
                className="cursor-pointer rounded px-1.5 py-0.5 font-mono text-[10px] text-foreground/80 transition-colors hover:bg-accent hover:text-foreground"
              >
                {view}
              </li>
            ))}
          </ul>
        </div>

        <div className="flex-1 overflow-auto bg-card">
          <PanelHeader>Templates</PanelHeader>
          <div className="space-y-1 p-1.5">
            {quickStartQueries.map((q, i) => (
              <button
                key={`${q.label}-${i}`}
                onClick={() => setQuery(q.query)}
                className="block w-full rounded border border-border bg-muted/50 px-2 py-1 text-left transition-colors hover:border-primary/50 hover:bg-muted"
              >
                <span className="block text-[10px] font-medium text-foreground">
                  {q.label}
                </span>
                <code className="block truncate text-[9px] text-muted-foreground">
                  {q.query.slice(0, 35)}…
                </code>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
