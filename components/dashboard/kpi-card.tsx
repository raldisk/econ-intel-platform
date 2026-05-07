"use client"

import { cn } from "@/lib/utils"
import { TrendingUp, TrendingDown, Minus } from "lucide-react"

interface KPICardProps {
  title: string
  value: string
  change?: number
  trend?: "up" | "down" | "neutral"
  className?: string
}

export function KPICard({
  title,
  value,
  change,
  trend = "neutral",
  className,
}: KPICardProps) {
  const TrendIcon = trend === "up" ? TrendingUp : trend === "down" ? TrendingDown : Minus
  const trendColor =
    trend === "up"
      ? "text-positive"
      : trend === "down"
        ? "text-negative"
        : "text-muted-foreground"

  return (
    <div
      className={cn(
        "group rounded-sm border border-border/60 bg-card px-3 py-2 transition-all hover:border-border hover:bg-card/80",
        className
      )}
    >
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] font-medium text-foreground/50 leading-none">
          {title}
        </span>
        {trend !== "neutral" && (
          <TrendIcon className={cn("h-3 w-3 opacity-70", trendColor)} />
        )}
      </div>
      <div className="flex items-baseline gap-2">
        <span className="text-lg font-semibold tabular-nums text-foreground leading-none tracking-tight">
          {value}
        </span>
        {change !== undefined && (
          <span className={cn("text-[11px] font-medium tabular-nums", trendColor)}>
            {change > 0 ? "+" : ""}
            {change.toFixed(2)}%
          </span>
        )}
      </div>
    </div>
  )
}
