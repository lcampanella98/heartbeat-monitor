'use client'

import { useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { useEndpoint, useIncident, useRecentChecks, useGeneratePostmortem, useUpdatePostmortem } from '@/lib/queries'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { formatDuration, formatTimestamp } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { CheckResult } from '@/types'

// ---- Timeline row ----

function TimelineRow({ check }: { check: CheckResult }) {
  const isSuccess = check.outcome === 'success'
  return (
    <div className="flex items-start gap-3 py-2 px-3 rounded-md hover:bg-muted/20 transition-colors">
      <div
        className={cn(
          'w-2 h-2 rounded-full mt-1 shrink-0',
          isSuccess ? 'bg-success' : 'bg-danger',
        )}
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-3 flex-wrap">
          <span
            className={cn(
              'text-xs font-mono font-medium',
              isSuccess ? 'text-success' : 'text-danger',
            )}
          >
            {check.outcome}
          </span>
          <span className="text-xs font-mono text-muted-foreground">
            {formatTimestamp(check.checked_at)}
          </span>
          <span className="text-xs font-mono text-muted-foreground/60">
            {check.latency_ms}ms
          </span>
          {check.status_code && (
            <span className="text-xs font-mono text-muted-foreground/60">
              HTTP {check.status_code}
            </span>
          )}
        </div>
        {check.error_message && (
          <p className="text-xs text-muted-foreground mt-0.5 truncate">{check.error_message}</p>
        )}
      </div>
    </div>
  )
}

// ---- Postmortem panel ----

function PostmortemPanel({ incidentId, content, generatedAt, editedAt }: {
  incidentId: number
  content: string | null
  generatedAt: string | null
  editedAt: string | null
}) {
  const generate = useGeneratePostmortem()
  const updatePm = useUpdatePostmortem()
  const [editContent, setEditContent] = useState(content ?? '')
  const [showConfirm, setShowConfirm] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  const handleGenerate = async () => {
    setError(null)
    try {
      await generate.mutateAsync(incidentId)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Generation failed')
    }
  }

  const handleSave = async () => {
    setError(null)
    try {
      await updatePm.mutateAsync({ incidentId, content: editContent })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Save failed')
    }
  }

  const handleRegenerate = async () => {
    setShowConfirm(false)
    setError(null)
    try {
      await generate.mutateAsync(incidentId)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Generation failed')
    }
  }

  const hasContent = content !== null

  return (
    <div className="bg-card border border-border rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <h2 className="text-sm font-medium">Postmortem draft</h2>
        <div className="flex items-center gap-2">
          {generatedAt && (
            <span className="text-xs text-muted-foreground font-mono">
              Generated {formatTimestamp(generatedAt)}
            </span>
          )}
          {editedAt && (
            <Badge variant="outline" className="text-[10px] font-mono px-1.5">
              Edited
            </Badge>
          )}
        </div>
      </div>

      <div className="p-4">
        {!hasContent ? (
          <div className="flex flex-col items-center justify-center py-8 text-center gap-3">
            <p className="text-sm text-muted-foreground">
              No postmortem yet. Generate one from the incident timeline.
            </p>
            {error && <p className="text-xs text-danger">{error}</p>}
            <Button
              size="sm"
              onClick={handleGenerate}
              disabled={generate.isPending}
            >
              {generate.isPending ? 'Generating…' : 'Generate postmortem'}
            </Button>
          </div>
        ) : (
          <div className="space-y-3">
            <Textarea
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
              rows={10}
              className="font-mono text-xs resize-none min-h-40"
            />
            {error && <p className="text-xs text-danger">{error}</p>}
            <div className="flex items-center justify-between">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowConfirm(true)}
                className="text-xs"
              >
                Regenerate
              </Button>
              <Button
                size="sm"
                onClick={handleSave}
                disabled={updatePm.isPending || editContent === content}
              >
                {saved ? 'Saved' : updatePm.isPending ? 'Saving…' : 'Save changes'}
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* Regenerate confirm dialog */}
      <Dialog open={showConfirm} onOpenChange={(o) => !o && setShowConfirm(false)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Regenerate postmortem?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground py-2">
            This will discard the current draft — including any edits you have made — and replace
            it with a freshly generated one. This cannot be undone.
          </p>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setShowConfirm(false)}>
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={handleRegenerate}
              disabled={generate.isPending}
            >
              {generate.isPending ? 'Generating…' : 'Regenerate'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// ---- Main page ----

export default function IncidentDetailClient() {
  const params = useParams<{ id: string }>()
  const incidentId = parseInt(params.id)
  const validId = !isNaN(incidentId)

  const { data: incident, isLoading } = useIncident(validId ? incidentId : 0, { refetchInterval: 2000 })

  const { data: endpoint } = useEndpoint(incident?.endpoint_id ?? 0)

  // Live checks — always fetched; relevant when incident is open
  const { data: liveChecks = [] } = useRecentChecks(
    incident?.endpoint_id ?? 0,
    200,
    { refetchInterval: 2000 },
  )

  if (isLoading) {
    return (
      <div className="p-6">
        <div className="h-8 w-48 bg-muted animate-pulse rounded" />
      </div>
    )
  }

  if (!incident) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        Incident not found.{' '}
        <Link href="/incidents" className="text-primary hover:underline">
          Back to incidents
        </Link>
      </div>
    )
  }

  const open = !incident.ended_at
  const timelineChecks: CheckResult[] = open
    ? liveChecks
    : (incident.frozen_timeline ?? [])

  return (
    <div className="p-6 max-w-3xl">
      {/* Breadcrumb */}
      <div className="flex items-center gap-1.5 mb-4 text-xs font-mono text-muted-foreground">
        <Link href="/incidents" className="hover:text-foreground">Incidents</Link>
        <span className="text-muted-foreground/40">/</span>
        <span>#{incidentId}</span>
      </div>

      {/* Header card */}
      <div className="bg-card border rounded-lg p-4 mb-6" style={{
        borderColor: open ? 'color-mix(in oklch, var(--color-danger) 40%, transparent)' : undefined
      }}>
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              {open ? (
                <span className="inline-flex items-center gap-1.5 text-xs font-mono font-medium text-danger">
                  <span className="w-1.5 h-1.5 rounded-full bg-danger animate-pulse inline-block" />
                  Active incident
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 text-xs font-mono text-muted-foreground">
                  <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/50 inline-block" />
                  Closed incident
                </span>
              )}
            </div>
            {endpoint && (
              <Link
                href={`/endpoints/${endpoint.id}`}
                className="font-semibold hover:text-primary hover:underline"
              >
                {endpoint.name}
              </Link>
            )}
            {endpoint && (
              <p className="text-xs font-mono text-muted-foreground mt-0.5">{endpoint.url}</p>
            )}
          </div>
          <div className="text-right shrink-0">
            {incident.duration_seconds != null && (
              <p className="text-sm font-mono font-semibold">
                {formatDuration(incident.duration_seconds)}
              </p>
            )}
          </div>
        </div>

        <div className="mt-3 grid grid-cols-2 sm:grid-cols-3 gap-3 pt-3 border-t border-border/50 text-xs">
          <div>
            <p className="text-muted-foreground font-mono mb-0.5">Started</p>
            <p className="font-mono">{formatTimestamp(incident.started_at)}</p>
          </div>
          {incident.ended_at && (
            <div>
              <p className="text-muted-foreground font-mono mb-0.5">Ended</p>
              <p className="font-mono">{formatTimestamp(incident.ended_at)}</p>
            </div>
          )}
          <div>
            <p className="text-muted-foreground font-mono mb-0.5">Timeline checks</p>
            <p className="font-mono">{timelineChecks.length}</p>
          </div>
        </div>
      </div>

      {/* Timeline */}
      <div className="bg-card border border-border rounded-lg overflow-hidden mb-6">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <h2 className="text-sm font-medium">
            Check timeline
            {open && (
              <span className="ml-2 text-xs font-mono text-muted-foreground">
                — live
              </span>
            )}
          </h2>
          <span className="text-xs font-mono text-muted-foreground">
            {timelineChecks.length} checks
          </span>
        </div>

        {timelineChecks.length === 0 ? (
          <div className="px-4 py-8 text-center text-xs text-muted-foreground font-mono">
            {open ? 'Loading live checks…' : 'No timeline data'}
          </div>
        ) : (
          <div className="px-2 py-2 max-h-80 overflow-y-auto">
            {timelineChecks.map((check) => (
              <TimelineRow key={check.id} check={check} />
            ))}
          </div>
        )}
      </div>

      {/* Postmortem */}
      <PostmortemPanel
        key={incident.postmortem?.generated_at ?? 'none'}
        incidentId={incidentId}
        content={incident.postmortem?.content ?? null}
        generatedAt={incident.postmortem?.generated_at ?? null}
        editedAt={incident.postmortem?.edited_at ?? null}
      />
    </div>
  )
}
