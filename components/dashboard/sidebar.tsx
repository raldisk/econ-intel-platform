"use client"

import { cn } from "@/lib/utils"
import {
  BarChart3,
  Database,
  LineChart,
  Settings,
  TrendingUp,
  Activity,
  ChevronLeft,
  ChevronRight,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { SectionLabel } from "./ui-primitives"

interface SidebarProps {
  activeTab: "explorer" | "sql"
  onTabChange: (tab: "explorer" | "sql") => void
  collapsed: boolean
  onCollapsedChange: (collapsed: boolean) => void
}

const navItems = [
  { id: "explorer" as const, label: "Explorer", icon: LineChart },
  { id: "sql" as const, label: "SQL", icon: Database },
]

const futureItems = [
  { label: "Markets", icon: TrendingUp },
  { label: "Rates", icon: Activity },
  { label: "Sentiment", icon: BarChart3 },
  { label: "Settings", icon: Settings },
]

export function DashboardSidebar({
  activeTab,
  onTabChange,
  collapsed,
  onCollapsedChange,
}: SidebarProps) {
  return (
    <aside
      className={cn(
        "flex flex-col border-r border-sidebar-border bg-sidebar transition-all duration-200",
        collapsed ? "w-10" : "w-36"
      )}
    >
      {/* Logo */}
      <div className="flex h-8 items-center border-b border-sidebar-border px-2">
        <div className="flex items-center gap-1.5">
          <div className="flex h-5 w-5 items-center justify-center rounded bg-primary/10">
            <BarChart3 className="h-3 w-3 text-primary" />
          </div>
          {!collapsed && (
            <span className="text-[10px] font-semibold text-sidebar-foreground">
              PH Intel
            </span>
          )}
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-1">
        {!collapsed && <SectionLabel>Workspaces</SectionLabel>}
        <div className="space-y-0.5">
          {navItems.map((item) => (
            <button
              key={item.id}
              onClick={() => onTabChange(item.id)}
              className={cn(
                "flex w-full items-center gap-1.5 rounded px-2 py-1 text-[10px] font-medium transition-colors",
                activeTab === item.id
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
              )}
            >
              <item.icon className="h-3 w-3 shrink-0" />
              {!collapsed && <span>{item.label}</span>}
            </button>
          ))}
        </div>

        {!collapsed && <SectionLabel className="mt-2">Soon</SectionLabel>}
        <div className="space-y-0.5">
          {futureItems.map((item) => (
            <button
              key={item.label}
              disabled
              className="flex w-full items-center gap-1.5 rounded px-2 py-1 text-[10px] font-medium text-sidebar-foreground/30 cursor-not-allowed"
            >
              <item.icon className="h-3 w-3 shrink-0" />
              {!collapsed && <span>{item.label}</span>}
            </button>
          ))}
        </div>
      </nav>

      {/* Collapse Button */}
      <div className="border-t border-sidebar-border p-1">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onCollapsedChange(!collapsed)}
          className="w-full h-5 justify-center text-sidebar-foreground/60 hover:text-sidebar-foreground"
        >
          {collapsed ? (
            <ChevronRight className="h-3 w-3" />
          ) : (
            <ChevronLeft className="h-3 w-3" />
          )}
        </Button>
      </div>
    </aside>
  )
}
