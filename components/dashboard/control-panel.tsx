"use client"

import { Database, Calendar, BarChart3, Download } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  PanelHeader,
  CollapsibleSection,
  Field,
  SelectInput,
  DateInput,
  ButtonGroup,
} from "./ui-primitives"

interface ControlPanelProps {
  views: string[]
  selectedView: string
  onViewChange: (view: string) => void
  columns: string[]
  xColumn: string
  yColumn: string
  onXColumnChange: (col: string) => void
  onYColumnChange: (col: string) => void
  chartType: "line" | "area" | "bar"
  onChartTypeChange: (type: "line" | "area" | "bar") => void
  dateRange?: { start: string; end: string }
  onDateRangeChange: (range: { start: string; end: string }) => void
  onRender: () => void
  onExportCSV: () => void
}

export function ControlPanel({
  views,
  selectedView,
  onViewChange,
  columns,
  xColumn,
  yColumn,
  onXColumnChange,
  onYColumnChange,
  chartType,
  onChartTypeChange,
  dateRange = { start: "", end: "" },
  onDateRangeChange,
  onRender,
  onExportCSV,
}: ControlPanelProps) {
  return (
    <div className="flex h-full flex-col overflow-y-auto border-r border-border bg-card">
      <PanelHeader>Controls</PanelHeader>

      <div className="flex-1 overflow-y-auto">
        <CollapsibleSection
          title="Data Source"
          icon={<Database className="h-3 w-3" />}
          defaultOpen
        >
          <Field label="View / Table">
            <SelectInput
              value={selectedView}
              options={views}
              onChange={onViewChange}
            />
          </Field>
          <p className="mt-1 text-[10px] text-muted-foreground">
            {columns.length} columns
          </p>
        </CollapsibleSection>

        <CollapsibleSection
          title="Time Range"
          icon={<Calendar className="h-3 w-3" />}
          defaultOpen
        >
          <div className="grid grid-cols-2 gap-1.5">
            <Field label="Start">
              <DateInput
                value={dateRange.start}
                onChange={(v) => onDateRangeChange({ ...dateRange, start: v })}
              />
            </Field>
            <Field label="End">
              <DateInput
                value={dateRange.end}
                onChange={(v) => onDateRangeChange({ ...dateRange, end: v })}
              />
            </Field>
          </div>
        </CollapsibleSection>

        <CollapsibleSection
          title="Chart Config"
          icon={<BarChart3 className="h-3 w-3" />}
          defaultOpen
        >
          <div className="space-y-1.5">
            <Field label="X Axis">
              <SelectInput
                value={xColumn}
                options={columns}
                onChange={onXColumnChange}
              />
            </Field>
            <Field label="Y Axis">
              <SelectInput
                value={yColumn}
                options={columns}
                onChange={onYColumnChange}
              />
            </Field>
            <Field label="Chart Type">
              <ButtonGroup
                options={[
                  { value: "line", label: "Line" },
                  { value: "area", label: "Area" },
                  { value: "bar", label: "Bar" },
                ]}
                value={chartType}
                onChange={(v) => onChartTypeChange(v as "line" | "area" | "bar")}
              />
            </Field>
          </div>
        </CollapsibleSection>

        <CollapsibleSection
          title="Export"
          icon={<Download className="h-3 w-3" />}
          defaultOpen={false}
        >
          <Button
            variant="secondary"
            size="sm"
            onClick={onExportCSV}
            className="w-full h-6 text-[10px]"
          >
            <Download className="mr-1 h-3 w-3" />
            Download CSV
          </Button>
        </CollapsibleSection>
      </div>

      <div className="border-t border-border p-2">
        <Button onClick={onRender} className="w-full h-6 text-[10px]">
          Render
        </Button>
      </div>
    </div>
  )
}
