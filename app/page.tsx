"use client"

import { useState, useEffect } from "react"
import { DashboardSidebar } from "@/components/dashboard/sidebar"
import { Header } from "@/components/dashboard/header"
import { ExplorerWorkspace } from "@/components/dashboard/explorer-workspace"
import { SQLEditor } from "@/components/dashboard/sql-editor"
import { api } from "@/lib/api"

const FALLBACK_VIEWS = [
  "psx_prices", "bsp_policy_rate", "fx_rates"
]

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState<"explorer" | "sql">("explorer")
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  const [availableViews, setAvailableViews] = useState<string[]>(FALLBACK_VIEWS)

  // Load available views
  useEffect(() => {
    api.listViews()
      .then((res) => {
        const names = res.views.map((v: any) => v.name)
        if (names.length > 0) setAvailableViews(names)
      })
      .catch(() => {})
  }, [])

  const handleRefresh = () => {
    window.location.reload()
  }

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <DashboardSidebar
        activeTab={activeTab}
        onTabChange={setActiveTab}
        collapsed={sidebarCollapsed}
        onCollapsedChange={setSidebarCollapsed}
      />

      <div className="flex flex-1 flex-col overflow-hidden">
        <Header onRefresh={handleRefresh} />

        <main className="flex-1 overflow-hidden">
          {activeTab === "explorer" ? (
            <ExplorerWorkspace />
          ) : (
            <SQLEditor
              availableViews={availableViews}
            />
          )}
        </main>
      </div>
    </div>
  )
}