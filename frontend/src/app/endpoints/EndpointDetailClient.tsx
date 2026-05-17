'use client'

import { useState } from 'react'
import Link from 'next/link'
import {
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
// Recharts v3 TooltipProps changed — use a flexible type
type TooltipArgs = { active?: boolean; payload?: Array<{ payload: HistoryBin }> }
import { useEndpoint, useEndpointHistory, useRecentChecks } from '@/lib/queries'
import { Badge } from '@/components/ui/badge'
import { formatAxisTime, formatTimestamp, formatUptime } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { HistoryBin } from '@/types'

type Range = '1h' | '1d' | '7d' | '30d' | '90d' | '1y'

const RANGES: { value: Range; label: string }[] = [
  { value: '1h', label: '1h' },
  { value: '1d', label: '1d' },
  { value: '7d', label: '7d' },
  { value: '30d', label: '30d' },
  { value: '90d', label: '90d' },
  { value: '1y', label: '1y' },
]

function barColor(uptime: number): string {
  if (uptime >= 99.9) return 'var(--color-success)'
  if (uptime >= 95) return 'var(--color-warning)'
  return 'var(--color-danger)'
}

function HistoryTooltip({ active, payload }: TooltipArgs) {
  if (!active || !payload?.length) return null
  const bin = payload[0]?.payload as HistoryBin
  return (
    <div className="bg-popover border border-border rounded-lg px-3 py-2 text-xs shadow-lg">
      <p className="font-mono text-muted-foreground mb-1">
        {formatTimestamp(bin.bucket_start)}
      </p>
      <p className="font-semibold text-sm">
        <span
          className={cn(
            bin.uptime_pct >= 99.9
              ? 'text-success'
              : bin.uptime_pct >= 95
                ? 'text-warning'
                : 'text-danger',
          )}
        >
          {formatUptime(bin.uptime_pct)}
        </span>
        {' '}uptime
      </p>
      <p className="text-muted-foreground mt-0.5">
        {bin.total_checks} checks &mdash; {bin.successful_checks} ok, {bin.failed_checks} failed
      </p>
      <p className="text-muted-foreground/60 capitalize">{bin.source} data</p>
    </div>
  )
}

export default function EndpointDetailClient({ endpointId }: { endpointId: number }) {
  const [range, setRange] = useState<Range>('7d')

  const { data: endpoint, isLoading: epLoading } = useEndpoint(endpointId)
  const { data: history = [], isLoading: histLoading } = useEndpointHistory(endpointId, range)
  const { data: checks = [] } = useRecentChecks(endpointId, 100)

  if (epLoading) {
    return (
      <div className="p-6">
        <div className="h-8 w-48 bg-muted animate-pulse rounded" />
      </div>
    )
  }

  if (!endpoint) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        Endpoint not found.{' '}
        <Link href="/endpoints" className="text-primary hover:underline">
          Back to endpoints
        </Link>
      </div>
    )
  }

  const source = history[0]?.source ?? 'raw'
  const tickFormatter = (v: string) => formatAxisTime(v, source)

  return (
    <div className="p-6 max-w-4xl">
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <a
              href="/endpoints"
              className="text-xs text-muted-foreground hover:text-foreground font-mono"
            >
              Endpoints
            </a>
            <span className="text-muted-foreground/40 text-xs">/</span>
            <span className="text-xs text-muted-foreground font-mono">{endpoint.name}</span>
          </div>
          <h1 className="text-lg font-semibold">{endpoint.name}</h1>
          <p className="text-xs font-mono text-muted-foreground mt-0.5">{endpoint.url}</p>
        </div>
        <div className="flex items-center gap-2">
          {endpoint.current_streak_outcome === 'success' && (
            <Badge className="bg-success text-success-foreground border-0 font-mono text-[10px]">
              UP
            </Badge>
          )}
          {endpoint.current_streak_outcome === 'failure' && (
            <Badge className="bg-danger text-danger-foreground border-0 font-mono text-[10px]">
              DOWN
            </Badge>
          )}
          {endpoint.current_streak_outcome === null && (
            <Badge variant="outline" className="font-mono text-[10px] text-muted-foreground">
              UNKNOWN
            </Badge>
          )}
          {!endpoint.enabled && (
            <Badge variant="outline" className="font-mono text-[10px] text-muted-foreground">
              DISABLED
            </Badge>
          )}
        </div>
      </div>

      {/* History chart */}
      <div className="bg-card border border-border rounded-lg p-4 mb-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-medium">Uptime history</h2>
          <div className="flex gap-0.5 bg-muted rounded-md p-0.5">
            {RANGES.map((r) => (
              <button
                key={r.value}
                onClick={() => setRange(r.value)}
                className={cn(
                  'px-2.5 py-1 text-xs font-mono rounded transition-colors',
                  range === r.value
                    ? 'bg-background text-foreground shadow-sm'
                    : 'text-muted-foreground hover:text-foreground',
                )}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>

        {histLoading ? (
          <div className="h-48 flex items-center justify-center">
            <span className="text-xs text-muted-foreground font-mono">Loading…</span>
          </div>
        ) : history.length === 0 ? (
          <div className="h-48 flex items-center justify-center">
            <span className="text-xs text-muted-foreground font-mono">No data for this range</span>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={history} margin={{ top: 4, right: 20, bottom: 0, left: 0 }}>
              <CartesianGrid
                vertical={false}
                stroke="var(--color-border)"
                strokeOpacity={0.5}
              />
              <XAxis
                dataKey="bucket_start"
                tickFormatter={tickFormatter}
                tick={{ fontSize: 10, fill: 'var(--color-muted-foreground)', fontFamily: 'var(--font-mono)' }}
                tickLine={false}
                axisLine={false}
                interval="preserveStartEnd"
              />
              <YAxis
                domain={[0, 100]}
                tickFormatter={(v) => `${v}%`}
                tick={{ fontSize: 10, fill: 'var(--color-muted-foreground)', fontFamily: 'var(--font-mono)' }}
                tickLine={false}
                axisLine={false}
                width={40}
              />
              <Tooltip content={<HistoryTooltip />} cursor={{ fill: 'var(--color-muted)', fillOpacity: 0.3 }} />
              <Bar dataKey="uptime_pct" radius={[2, 2, 0, 0]} maxBarSize={20}>
                {history.map((entry, i) => (
                  <Cell key={i} fill={barColor(entry.uptime_pct)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Recent checks table */}
      <div className="bg-card border border-border rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-border">
          <h2 className="text-sm font-medium">Recent checks</h2>
        </div>
        {checks.length === 0 ? (
          <div className="px-4 py-8 text-center text-xs text-muted-foreground font-mono">
            No checks yet
          </div>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border bg-muted/20 font-mono text-muted-foreground">
                <th className="text-left px-4 py-2 font-medium">Time</th>
                <th className="text-left px-4 py-2 font-medium">Outcome</th>
                <th className="text-left px-4 py-2 font-medium">Latency</th>
                <th className="text-left px-4 py-2 font-medium hidden sm:table-cell">Status</th>
                <th className="text-left px-4 py-2 font-medium hidden md:table-cell">Error</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {checks.map((check) => (
                <tr key={check.id} className="hover:bg-muted/10">
                  <td className="px-4 py-2 font-mono text-muted-foreground">
                    {formatTimestamp(check.checked_at)}
                  </td>
                  <td className="px-4 py-2">
                    <span
                      className={cn(
                        'font-mono',
                        check.outcome === 'success' ? 'text-success' : 'text-danger',
                      )}
                    >
                      {check.outcome}
                    </span>
                  </td>
                  <td className="px-4 py-2 font-mono text-muted-foreground">
                    {check.latency_ms}ms
                  </td>
                  <td className="px-4 py-2 font-mono text-muted-foreground hidden sm:table-cell">
                    {check.status_code ?? '—'}
                  </td>
                  <td className="px-4 py-2 text-muted-foreground hidden md:table-cell truncate max-w-xs">
                    {check.error_category ? (
                      <span className="font-mono text-danger/70">{check.error_category}</span>
                    ) : (
                      '—'
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
