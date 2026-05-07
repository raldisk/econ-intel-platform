"use client"

import { useState } from "react"
import { cn } from "@/lib/utils"
import { ChevronDown, ChevronUp, ChevronsUpDown } from "lucide-react"

interface Column {
  key: string
  label: string
  align?: "left" | "center" | "right"
  format?: (value: unknown) => string
}

interface DataTableProps {
  columns: Column[]
  data: Record<string, unknown>[]
  className?: string
  maxHeight?: string
}

export function DataTable({
  columns,
  data,
  className,
  maxHeight = "400px",
}: DataTableProps) {
  const [sortKey, setSortKey] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc")

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc")
    } else {
      setSortKey(key)
      setSortDir("asc")
    }
  }

  const sortedData = [...data].sort((a, b) => {
    if (!sortKey) return 0
    const aVal = a[sortKey]
    const bVal = b[sortKey]
    if (aVal === bVal) return 0
    if (aVal === null || aVal === undefined) return 1
    if (bVal === null || bVal === undefined) return -1
    const comparison = aVal < bVal ? -1 : 1
    return sortDir === "asc" ? comparison : -comparison
  })

  const formatValue = (col: Column, value: unknown) => {
    if (value === null || value === undefined) return "—"
    if (col.format) return col.format(value)
    if (typeof value === "number") {
      return value.toLocaleString(undefined, { maximumFractionDigits: 4 })
    }
    return String(value)
  }

  const getChangeClass = (value: unknown) => {
    if (typeof value !== "number") return ""
    if (value > 0) return "text-positive"
    if (value < 0) return "text-negative"
    return ""
  }

  return (
    <div
      className={cn("overflow-auto rounded-sm border border-border/60", className)}
      style={{ maxHeight }}
    >
      <table className="w-full border-collapse text-[11px]">
        <thead className="sticky top-0 z-10 bg-muted/80 backdrop-blur-sm">
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                onClick={() => handleSort(col.key)}
                className={cn(
                  "cursor-pointer border-b border-border px-3 py-2 font-medium text-foreground/50 transition-colors hover:text-foreground whitespace-nowrap text-left",
                  col.align === "right" && "text-right",
                  col.align === "center" && "text-center"
                )}
              >
                <div
                  className={cn(
                    "flex items-center gap-1",
                    col.align === "right" && "justify-end",
                    col.align === "center" && "justify-center"
                  )}
                >
                  <span>{col.label}</span>
                  {sortKey === col.key ? (
                    sortDir === "asc" ? (
                      <ChevronUp className="h-3 w-3" />
                    ) : (
                      <ChevronDown className="h-3 w-3" />
                    )
                  ) : (
                    <ChevronsUpDown className="h-3 w-3 opacity-30" />
                  )}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border/30">
          {sortedData.map((row, i) => (
            <tr
              key={i}
              className={cn(
                "transition-colors hover:bg-accent/30",
                i % 2 === 1 && "bg-muted/5"
              )}
            >
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={cn(
                    "px-3 py-1.5 tabular-nums whitespace-nowrap",
                    col.align === "right" && "text-right font-mono",
                    col.align === "center" && "text-center",
                    col.key.includes("change") && getChangeClass(row[col.key])
                  )}
                >
                  {formatValue(col, row[col.key])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {data.length === 0 && (
        <div className="flex h-20 items-center justify-center text-[11px] text-foreground/40">
          No data available
        </div>
      )}
    </div>
  )
}
