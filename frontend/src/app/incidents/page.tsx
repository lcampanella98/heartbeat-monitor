'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useEndpoints, useIncidents } from '@/lib/queries'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { formatDuration, formatTimestamp } from '@/lib/format'

type StateFilter = 'all' | 'active' | 'closed'

export default function IncidentsPage() {
  const [stateFilter, setStateFilter] = useState<StateFilter>('all')
  const [endpointFilter, setEndpointFilter] = useState<string>('all')

  const handleStateChange = (v: string | null) => setStateFilter((v ?? 'all') as StateFilter)
  const handleEndpointChange = (v: string | null) => setEndpointFilter(v ?? 'all')

  const { data: endpoints = [] } = useEndpoints()
  const endpointMap = new Map(endpoints.map((ep) => [ep.id, ep]))

  const { data: incidents = [], isLoading } = useIncidents({
    state: stateFilter === 'all' ? undefined : stateFilter,
    endpoint_id: endpointFilter !== 'all' ? parseInt(endpointFilter) : undefined,
  })

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-lg font-semibold">Incidents</h1>
          <p className="text-xs text-muted-foreground mt-0.5 font-mono">
            {incidents.length} result{incidents.length !== 1 ? 's' : ''}
          </p>
        </div>

        {/* Filters */}
        <div className="flex items-center gap-2">
          <Select value={stateFilter} onValueChange={handleStateChange}>
            <SelectTrigger className="h-7 text-xs font-mono w-28">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              <SelectItem value="active">Active</SelectItem>
              <SelectItem value="closed">Closed</SelectItem>
            </SelectContent>
          </Select>

          {endpoints.length > 0 && (
            <Select value={endpointFilter} onValueChange={handleEndpointChange}>
              <SelectTrigger className="h-7 text-xs font-mono w-40">
                <SelectValue placeholder="All endpoints" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All endpoints</SelectItem>
                {endpoints.map((ep) => (
                  <SelectItem key={ep.id} value={String(ep.id)}>
                    {ep.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-14 bg-card border border-border rounded-lg animate-pulse" />
          ))}
        </div>
      ) : incidents.length === 0 ? (
        <div className="text-center py-20 text-muted-foreground">
          <p className="text-sm">No incidents found.</p>
        </div>
      ) : (
        <div className="border border-border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/30 text-xs text-muted-foreground font-mono">
                <th className="text-left px-4 py-2.5 font-medium">Endpoint</th>
                <th className="text-left px-4 py-2.5 font-medium">Status</th>
                <th className="text-left px-4 py-2.5 font-medium hidden sm:table-cell">
                  Started
                </th>
                <th className="text-left px-4 py-2.5 font-medium hidden md:table-cell">
                  Ended
                </th>
                <th className="text-left px-4 py-2.5 font-medium hidden lg:table-cell">
                  Duration
                </th>
                <th className="text-left px-4 py-2.5 font-medium hidden xl:table-cell">
                  Postmortem
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {incidents.map((incident) => {
                const ep = endpointMap.get(incident.endpoint_id)
                const isOpen = !incident.ended_at

                return (
                  <tr key={incident.id} className="hover:bg-muted/20 transition-colors">
                    <td className="px-4 py-3">
                      <Link
                        href={`/incidents/${incident.id}`}
                        className="font-medium hover:text-primary hover:underline"
                      >
                        {ep?.name ?? `Endpoint #${incident.endpoint_id}`}
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      {isOpen ? (
                        <span className="inline-flex items-center gap-1.5 text-xs font-mono text-danger">
                          <span className="w-1.5 h-1.5 rounded-full bg-danger animate-pulse inline-block" />
                          Active
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1.5 text-xs font-mono text-muted-foreground">
                          <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/50 inline-block" />
                          Closed
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-muted-foreground hidden sm:table-cell">
                      {formatTimestamp(incident.started_at)}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-muted-foreground hidden md:table-cell">
                      {incident.ended_at ? formatTimestamp(incident.ended_at) : '—'}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-muted-foreground hidden lg:table-cell">
                      {incident.duration_seconds != null
                        ? formatDuration(incident.duration_seconds)
                        : '—'}
                    </td>
                    <td className="px-4 py-3 hidden xl:table-cell">
                      {incident.postmortem?.content ? (
                        <Badge
                          variant="outline"
                          className="text-[10px] px-1.5 font-mono text-muted-foreground"
                        >
                          Generated
                        </Badge>
                      ) : (
                        <span className="text-xs text-muted-foreground/40 font-mono">—</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
