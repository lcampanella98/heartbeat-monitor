'use client'

import Link from 'next/link'
import { useEndpoints, useIncidents, useRecentChecks, useEndpointUptime } from '@/lib/queries'
import { Badge } from '@/components/ui/badge'
import { RecentCheckStrip } from '@/components/RecentCheckStrip'
import { formatInterval, formatTimestamp, formatUptime } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { Endpoint, Incident } from '@/types'

function StateBadge({ outcome }: { outcome: string | null }) {
  if (outcome === 'success')
    return (
      <Badge className="bg-success text-success-foreground border-0 font-mono text-[10px] px-1.5">
        UP
      </Badge>
    )
  if (outcome === 'failure')
    return (
      <Badge className="bg-danger text-danger-foreground border-0 font-mono text-[10px] px-1.5">
        DOWN
      </Badge>
    )
  return (
    <Badge variant="outline" className="font-mono text-[10px] px-1.5 text-muted-foreground">
      UNKNOWN
    </Badge>
  )
}

function UptimeChip({
  label,
  value,
}: {
  label: string
  value: number | undefined
}) {
  if (value === undefined)
    return (
      <span className="font-mono text-xs text-muted-foreground/50">
        {label}: —
      </span>
    )
  const color =
    value >= 99.9
      ? 'text-success'
      : value >= 95
        ? 'text-warning'
        : 'text-danger'
  return (
    <span className="font-mono text-xs text-muted-foreground">
      {label}:{' '}
      <span className={color}>{formatUptime(value)}</span>
    </span>
  )
}

function EndpointCard({
  endpoint,
  activeIncidents,
}: {
  endpoint: Endpoint
  activeIncidents: Incident[]
}) {
  const { data: checks = [] } = useRecentChecks(endpoint.id, 60, { refetchInterval: 5000 })
  const { data: uptime } = useEndpointUptime(endpoint.id, { refetchInterval: 5000 })
  const isDown = endpoint.current_streak_outcome === 'failure'
  const hasIncident = activeIncidents.some((i) => i.endpoint_id === endpoint.id)

  return (
    <Link
      href={`/endpoints/${endpoint.id}`}
      className={cn(
        'block bg-card rounded-lg p-4 border transition-all group',
        'hover:border-primary/30 hover:bg-card/70',
        hasIncident ? 'border-danger/40' : isDown ? 'border-danger/20' : 'border-border',
        !endpoint.enabled && 'opacity-50',
      )}
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-medium text-sm truncate">{endpoint.name}</span>
            {!endpoint.enabled && (
              <Badge variant="outline" className="text-[10px] px-1 py-0 font-mono shrink-0">
                OFF
              </Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground font-mono truncate mt-0.5">{endpoint.url}</p>
        </div>
        <StateBadge outcome={endpoint.current_streak_outcome} />
      </div>

      <RecentCheckStrip checks={checks} />

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="font-mono text-xs text-muted-foreground/60">
          {formatInterval(endpoint.check_interval_seconds)}
        </span>
        <UptimeChip label="24h" value={uptime?.h24} />
        <UptimeChip label="7d" value={uptime?.d7} />
        <UptimeChip label="30d" value={uptime?.d30} />
      </div>
    </Link>
  )
}

export default function DashboardPage() {
  const { data: endpoints = [], isLoading } = useEndpoints({ refetchInterval: 5000 })
  const { data: activeIncidents = [] } = useIncidents(
    { state: 'active' },
    { refetchInterval: 5000 },
  )

  const endpointMap = new Map(endpoints.map((ep) => [ep.id, ep]))

  return (
    <div className="p-6 max-w-screen-2xl">
      <div className="flex items-baseline justify-between mb-6">
        <div>
          <h1 className="text-lg font-semibold">Dashboard</h1>
          <p className="text-xs text-muted-foreground mt-0.5 font-mono">
            {endpoints.length} endpoint{endpoints.length !== 1 ? 's' : ''} monitored
          </p>
        </div>
        <Link
          href="/endpoints"
          className="text-xs text-primary hover:underline font-mono"
        >
          Manage endpoints
        </Link>
      </div>

      {activeIncidents.length > 0 && (
        <div className="border border-danger/30 bg-danger-subtle rounded-lg p-4 mb-6">
          <p className="text-xs font-mono font-medium text-danger mb-2 uppercase tracking-wider">
            {activeIncidents.length} active incident{activeIncidents.length !== 1 ? 's' : ''}
          </p>
          <div className="space-y-1.5">
            {activeIncidents.map((incident) => {
              const ep = endpointMap.get(incident.endpoint_id)
              return (
                <Link
                  key={incident.id}
                  href={`/incidents/${incident.id}`}
                  className="flex items-center gap-2.5 hover:underline group"
                >
                  <span className="inline-block w-1.5 h-1.5 rounded-full bg-danger shrink-0 animate-pulse" />
                  <span className="text-sm font-medium text-danger">
                    {ep?.name ?? `Endpoint #${incident.endpoint_id}`}
                  </span>
                  <span className="text-xs text-muted-foreground font-mono">
                    since {formatTimestamp(incident.started_at)}
                  </span>
                </Link>
              )
            })}
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="bg-card border border-border rounded-lg p-4 h-32 animate-pulse" />
          ))}
        </div>
      ) : endpoints.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <p className="text-sm text-muted-foreground">No endpoints configured.</p>
          <Link
            href="/endpoints"
            className="mt-3 text-sm text-primary hover:underline"
          >
            Add your first endpoint
          </Link>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {endpoints.map((ep) => (
            <EndpointCard key={ep.id} endpoint={ep} activeIncidents={activeIncidents} />
          ))}
        </div>
      )}
    </div>
  )
}
