"use client"

import { cn } from "@/lib/utils"
import { ChevronDown, ChevronRight } from "lucide-react"
import { useState } from "react"

// Consistent spacing constants
export const SPACING = {
  panel: "px-3 py-1.5",
  section: "px-3 py-2",
  sectionContent: "px-3 pb-2",
  cell: "px-2 py-1",
  gap: {
    xs: "gap-0.5",
    sm: "gap-1",
    md: "gap-1.5",
    lg: "gap-2",
  },
} as const

// Panel header - used at top of sidebars, editors, control panels
interface PanelHeaderProps {
  children: React.ReactNode
  className?: string
  actions?: React.ReactNode
}

export function PanelHeader({ children, className, actions }: PanelHeaderProps) {
  return (
    <div
      className={cn(
        "flex h-9 items-center justify-between border-b border-border bg-card/80 px-3",
        className
      )}
    >
      <span className="text-[11px] font-semibold uppercase tracking-wide text-foreground/70">
        {children}
      </span>
      {actions && <div className="flex items-center gap-1.5">{actions}</div>}
    </div>
  )
}

// Section header - used for collapsible sections in control panels
interface SectionHeaderProps {
  title: string
  icon?: React.ReactNode
  defaultOpen?: boolean
  children: React.ReactNode
  className?: string
}

export function CollapsibleSection({
  title,
  icon,
  defaultOpen = true,
  children,
  className,
}: SectionHeaderProps) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className={cn("border-b border-border/60", className)}>
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-[11px] font-medium text-foreground/60 transition-colors hover:text-foreground hover:bg-accent/30"
      >
        {icon}
        <span className="flex-1">{title}</span>
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 opacity-50" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 opacity-50" />
        )}
      </button>
      {open && <div className="px-3 pb-3 pt-1">{children}</div>}
    </div>
  )
}

// Field wrapper for form inputs
interface FieldProps {
  label: string
  children: React.ReactNode
  className?: string
}

export function Field({ label, children, className }: FieldProps) {
  return (
    <div className={cn("space-y-1", className)}>
      <label className="text-[10px] font-medium text-foreground/50 block">
        {label}
      </label>
      {children}
    </div>
  )
}

// Select input
interface SelectInputProps {
  value: string
  options: string[]
  onChange: (value: string) => void
  className?: string
}

export function SelectInput({ value, options, onChange, className }: SelectInputProps) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={cn(
        "w-full rounded-sm border border-border/80 bg-muted/50 px-2.5 py-1.5 text-[11px] text-foreground focus:outline-none focus:ring-1 focus:ring-ring transition-colors hover:border-border",
        className
      )}
    >
      {options.map((opt) => (
        <option key={opt} value={opt}>
          {opt}
        </option>
      ))}
    </select>
  )
}

// Date input
interface DateInputProps {
  value: string
  onChange: (value: string) => void
  className?: string
}

export function DateInput({ value, onChange, className }: DateInputProps) {
  return (
    <input
      type="date"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={cn(
        "w-full rounded-sm border border-border/80 bg-muted/50 px-2 py-1.5 text-[11px] text-foreground focus:outline-none focus:ring-1 focus:ring-ring transition-colors hover:border-border",
        className
      )}
    />
  )
}

// Status badge
interface StatusBadgeProps {
  variant: "positive" | "negative" | "neutral" | "warning"
  children: React.ReactNode
  dot?: boolean
  className?: string
}

export function StatusBadge({ variant, children, dot, className }: StatusBadgeProps) {
  const variantStyles = {
    positive: "bg-positive/15 text-positive",
    negative: "bg-negative/15 text-negative",
    neutral: "bg-muted/80 text-foreground/60",
    warning: "bg-warning/15 text-warning",
  }

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-[10px] font-medium",
        variantStyles[variant],
        className
      )}
    >
      {dot && (
        <span
          className={cn(
            "h-1.5 w-1.5 rounded-full animate-pulse",
            variant === "positive" && "bg-positive",
            variant === "negative" && "bg-negative",
            variant === "neutral" && "bg-foreground/50",
            variant === "warning" && "bg-warning"
          )}
        />
      )}
      {children}
    </span>
  )
}

// Section label (for nav groups, etc.)
interface SectionLabelProps {
  children: React.ReactNode
  className?: string
}

export function SectionLabel({ children, className }: SectionLabelProps) {
  return (
    <span
      className={cn(
        "block px-2 py-1 text-[9px] font-medium uppercase tracking-wider text-muted-foreground",
        className
      )}
    >
      {children}
    </span>
  )
}

// Empty state
interface EmptyStateProps {
  children: React.ReactNode
  className?: string
}

export function EmptyState({ children, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex h-full items-center justify-center text-xs text-muted-foreground",
        className
      )}
    >
      {children}
    </div>
  )
}

// Button group for chart type toggles, etc.
interface ButtonGroupProps {
  options: { value: string; label: string }[]
  value: string
  onChange: (value: string) => void
  className?: string
}

export function ButtonGroup({ options, value, onChange, className }: ButtonGroupProps) {
  return (
    <div className={cn("flex gap-1 rounded-sm bg-muted/30 p-0.5", className)}>
      {options.map((opt) => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          className={cn(
            "flex-1 rounded-sm px-2.5 py-1 text-[11px] font-medium transition-all",
            value === opt.value
              ? "bg-primary text-primary-foreground shadow-sm"
              : "text-foreground/60 hover:text-foreground hover:bg-accent/50"
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}
