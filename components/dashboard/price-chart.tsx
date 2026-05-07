"use client"

import { useMemo } from "react"
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { cn } from "@/lib/utils"

interface PriceChartProps {
  data: { date: string; value: number; volume?: number }[]
  type?: "line" | "area" | "bar"
  color?: string
  title?: string
  height?: number
  showVolume?: boolean
  className?: string
}

export function PriceChart({
  data,
  type = "area",
  color = "var(--chart-1)",
  title,
  height = 200,
  showVolume = false,
  className,
}: PriceChartProps) {
  const formattedData = useMemo(() => {
    return data.map((d) => ({
      ...d,
      date: new Date(d.date).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
      }),
    }))
  }, [data])

  const minValue = Math.min(...data.map((d) => d.value)) * 0.98
  const maxValue = Math.max(...data.map((d) => d.value)) * 1.02

  const CustomTooltip = ({
    active,
    payload,
    label,
  }: {
    active?: boolean
    payload?: { value: number; dataKey: string }[]
    label?: string
  }) => {
    if (!active || !payload?.length) return null
    return (
      <div className="rounded border border-border bg-popover px-2 py-1 shadow-lg">
        <p className="text-[10px] text-muted-foreground">{label}</p>
        {payload.map((p, i) => (
          <p key={i} className="text-xs font-medium tabular-nums">
            {p.dataKey === "value" ? "" : "Vol: "}
            {p.value.toLocaleString(undefined, { maximumFractionDigits: 2 })}
          </p>
        ))}
      </div>
    )
  }

  const renderChart = () => {
    const commonProps = {
      data: formattedData,
      margin: { top: 4, right: 4, left: 0, bottom: 0 },
    }

    const axisProps = {
      tickLine: false,
      axisLine: false,
      tick: { fill: "var(--muted-foreground)", fontSize: 9 },
    }

    if (type === "line") {
      return (
        <LineChart {...commonProps}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis dataKey="date" {...axisProps} />
          <YAxis domain={[minValue, maxValue]} {...axisProps} width={45} />
          <Tooltip content={<CustomTooltip />} />
          <Line
            type="monotone"
            dataKey="value"
            stroke={color}
            strokeWidth={1.5}
            dot={false}
            activeDot={{ r: 3, fill: color }}
          />
        </LineChart>
      )
    }

    if (type === "bar") {
      return (
        <BarChart {...commonProps}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis dataKey="date" {...axisProps} />
          <YAxis {...axisProps} width={45} />
          <Tooltip content={<CustomTooltip />} />
          <Bar dataKey="value" fill={color} radius={[2, 2, 0, 0]} />
        </BarChart>
      )
    }

    return (
      <AreaChart {...commonProps}>
        <defs>
          <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={color} stopOpacity={0.3} />
            <stop offset="95%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
        <XAxis dataKey="date" {...axisProps} />
        <YAxis domain={[minValue, maxValue]} {...axisProps} width={45} />
        <Tooltip content={<CustomTooltip />} />
        <Area
          type="monotone"
          dataKey="value"
          stroke={color}
          strokeWidth={1.5}
          fill="url(#colorValue)"
        />
      </AreaChart>
    )
  }

  return (
    <div className={cn("rounded-sm border border-border/60 bg-card p-3", className)}>
      {title && (
        <h3 className="mb-2 text-[11px] font-medium text-foreground/50">
          {title}
        </h3>
      )}
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          {renderChart()}
        </ResponsiveContainer>
      </div>
      {showVolume && data[0]?.volume !== undefined && (
        <div className="mt-1" style={{ height: 40 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={formattedData} margin={{ top: 0, right: 4, left: 0, bottom: 0 }}>
              <XAxis dataKey="date" hide />
              <YAxis hide />
              <Bar dataKey="volume" fill="var(--chart-3)" opacity={0.5} radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}
