"use client"

import { RefreshCw, Bell, HelpCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { StatusBadge } from "./ui-primitives"
import { cn } from "@/lib/utils"

interface HeaderProps {
  onRefresh?: () => void
  className?: string
}

export function Header({ onRefresh, className }: HeaderProps) {
  return (
    <header
      className={cn(
        "flex h-8 items-center justify-between border-b border-border bg-card px-3",
        className
      )}
    >
      <div className="flex items-center gap-2">
        <h1 className="text-xs font-semibold text-foreground">
          PH Economic Intelligence
        </h1>
        <div className="hidden items-center gap-1 sm:flex">
          <StatusBadge variant="positive" dot>
            Live
          </StatusBadge>
          <StatusBadge variant="neutral">DuckDB</StatusBadge>
        </div>
      </div>

      <div className="flex items-center">
        <Button
          variant="ghost"
          size="sm"
          onClick={onRefresh}
          className="h-6 w-6 p-0 text-muted-foreground hover:text-foreground"
        >
          <RefreshCw className="h-3 w-3" />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 w-6 p-0 text-muted-foreground hover:text-foreground"
        >
          <Bell className="h-3 w-3" />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 w-6 p-0 text-muted-foreground hover:text-foreground"
        >
          <HelpCircle className="h-3 w-3" />
        </Button>
      </div>
    </header>
  )
}
