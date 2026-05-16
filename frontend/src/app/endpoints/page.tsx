'use client'

import { useState } from 'react'
import { useForm, Controller } from 'react-hook-form'
import Link from 'next/link'
import {
  useEndpoints,
  useCreateEndpoint,
  useUpdateEndpoint,
  useDeleteEndpoint,
  useEnableEndpoint,
  useDisableEndpoint,
} from '@/lib/queries'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { formatInterval, formatRelativeTime } from '@/lib/format'
import type { Endpoint, SimOutageWindow } from '@/types'

// ---- Form types ----

interface EndpointFormValues {
  name: string
  url: string
  check_interval_seconds: number
  timeout_seconds: number
  enabled: boolean
  sim_failure_rate: number
  sim_latency_min_ms: number
  sim_latency_max_ms: number
}

function defaultValues(ep?: Endpoint): EndpointFormValues {
  return {
    name: ep?.name ?? '',
    url: ep?.url ?? '',
    check_interval_seconds: ep?.check_interval_seconds ?? 60,
    timeout_seconds: ep?.timeout_seconds ?? 10,
    enabled: ep?.enabled ?? true,
    sim_failure_rate: ep ? Math.round(ep.sim_failure_rate * 100) : 0,
    sim_latency_min_ms: ep?.sim_latency_min_ms ?? 100,
    sim_latency_max_ms: ep?.sim_latency_max_ms ?? 500,
  }
}

// ---- Field label ----

function FieldLabel({ children, error }: { children: React.ReactNode; error?: string }) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-muted-foreground">{children}</label>
      {error && <p className="text-xs text-danger">{error}</p>}
    </div>
  )
}

// ---- Outage window editor ----

function OutageWindowEditor({
  windows,
  onChange,
}: {
  windows: SimOutageWindow[]
  onChange: (w: SimOutageWindow[]) => void
}) {
  const add = () => onChange([...windows, { start: '00:00', end: '01:00' }])
  const remove = (i: number) => onChange(windows.filter((_, idx) => idx !== i))
  const update = (i: number, field: 'start' | 'end', value: string) => {
    const next = windows.map((w, idx) => (idx === i ? { ...w, [field]: value } : w))
    onChange(next)
  }

  return (
    <div className="space-y-2">
      {windows.map((w, i) => (
        <div key={i} className="flex items-center gap-2">
          <Input
            type="time"
            value={w.start}
            onChange={(e) => update(i, 'start', e.target.value)}
            className="h-7 text-xs font-mono w-28"
          />
          <span className="text-xs text-muted-foreground">to</span>
          <Input
            type="time"
            value={w.end}
            onChange={(e) => update(i, 'end', e.target.value)}
            className="h-7 text-xs font-mono w-28"
          />
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            onClick={() => remove(i)}
            className="text-muted-foreground hover:text-danger"
          >
            &times;
          </Button>
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" onClick={add} className="text-xs h-7">
        + Add window
      </Button>
    </div>
  )
}

// ---- Endpoint create/edit dialog ----

function EndpointDialog({
  endpoint,
  open,
  onClose,
}: {
  endpoint?: Endpoint
  open: boolean
  onClose: () => void
}) {
  const create = useCreateEndpoint()
  const update = useUpdateEndpoint(endpoint?.id ?? 0)
  const isEdit = !!endpoint

  const {
    register,
    handleSubmit,
    control,
    formState: { errors, isSubmitting },
  } = useForm<EndpointFormValues>({ defaultValues: defaultValues(endpoint) })

  const [outageWindows, setOutageWindows] = useState<SimOutageWindow[]>(
    endpoint?.sim_outage_windows ?? [],
  )
  const [showSim, setShowSim] = useState(false)
  const [apiError, setApiError] = useState<string | null>(null)

  const onSubmit = handleSubmit(async (data) => {
    setApiError(null)
    const payload = {
      name: data.name,
      url: data.url,
      check_interval_seconds: Number(data.check_interval_seconds) as 30 | 60 | 300 | 900,
      timeout_seconds: Number(data.timeout_seconds),
      enabled: data.enabled,
      sim_failure_rate: Number(data.sim_failure_rate) / 100,
      sim_latency_min_ms: Number(data.sim_latency_min_ms),
      sim_latency_max_ms: Number(data.sim_latency_max_ms),
      sim_outage_windows: outageWindows,
    }
    try {
      if (isEdit) {
        await update.mutateAsync(payload)
      } else {
        await create.mutateAsync(payload)
      }
      onClose()
    } catch (e: unknown) {
      setApiError(e instanceof Error ? e.message : 'An error occurred')
    }
  })

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEdit ? 'Edit endpoint' : 'New endpoint'}</DialogTitle>
        </DialogHeader>

        <form onSubmit={onSubmit} className="space-y-4 py-2">
          {/* Name */}
          <div className="space-y-1.5">
            <FieldLabel error={errors.name?.message}>Name</FieldLabel>
            <Input
              {...register('name', { required: 'Name is required' })}
              placeholder="api-prod"
              className="h-8"
            />
          </div>

          {/* URL */}
          <div className="space-y-1.5">
            <FieldLabel error={errors.url?.message}>URL</FieldLabel>
            <Input
              {...register('url', {
                required: 'URL is required',
                validate: (v) =>
                  v.startsWith('http://') || v.startsWith('https://')
                    ? true
                    : 'Must start with http:// or https://',
              })}
              placeholder="https://example.com/health"
              className="h-8 font-mono text-xs"
            />
          </div>

          {/* Interval + Timeout row */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <FieldLabel>Check interval</FieldLabel>
              <Controller
                name="check_interval_seconds"
                control={control}
                render={({ field }) => (
                  <Select
                    value={String(field.value)}
                    onValueChange={(v) => field.onChange(Number(v))}
                  >
                    <SelectTrigger className="h-8 w-full text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="30">30 seconds</SelectItem>
                      <SelectItem value="60">1 minute</SelectItem>
                      <SelectItem value="300">5 minutes</SelectItem>
                      <SelectItem value="900">15 minutes</SelectItem>
                    </SelectContent>
                  </Select>
                )}
              />
            </div>

            <div className="space-y-1.5">
              <FieldLabel error={errors.timeout_seconds?.message}>Timeout (s)</FieldLabel>
              <Input
                type="number"
                {...register('timeout_seconds', {
                  required: true,
                  valueAsNumber: true,
                  min: { value: 1, message: 'Min 1s' },
                  max: { value: 60, message: 'Max 60s' },
                })}
                className="h-8 font-mono"
              />
            </div>
          </div>

          {/* Enabled */}
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              {...register('enabled')}
              className="rounded border-input"
            />
            <span className="text-sm">Enabled</span>
          </label>

          {/* Simulator config collapsible */}
          <div className="border border-border rounded-lg overflow-hidden">
            <button
              type="button"
              onClick={() => setShowSim((s) => !s)}
              className="flex items-center justify-between w-full px-3 py-2.5 text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
            >
              <span>Simulator config</span>
              <span className="font-mono text-xs">{showSim ? '▲' : '▼'}</span>
            </button>

            {showSim && (
              <div className="px-3 py-3 space-y-3 border-t border-border bg-muted/20">
                <p className="text-xs text-muted-foreground">
                  Used only in simulated mode. Always editable.
                </p>

                {/* Failure rate */}
                <div className="space-y-1.5">
                  <FieldLabel error={errors.sim_failure_rate?.message}>
                    Failure rate (%)
                  </FieldLabel>
                  <Input
                    type="number"
                    step="0.1"
                    {...register('sim_failure_rate', {
                      valueAsNumber: true,
                      min: { value: 0, message: 'Min 0' },
                      max: { value: 100, message: 'Max 100' },
                    })}
                    className="h-8 font-mono w-32"
                  />
                </div>

                {/* Latency range */}
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <FieldLabel error={errors.sim_latency_min_ms?.message}>
                      Latency min (ms)
                    </FieldLabel>
                    <Input
                      type="number"
                      {...register('sim_latency_min_ms', {
                        valueAsNumber: true,
                        min: { value: 0, message: 'Min 0' },
                      })}
                      className="h-8 font-mono"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <FieldLabel error={errors.sim_latency_max_ms?.message}>
                      Latency max (ms)
                    </FieldLabel>
                    <Input
                      type="number"
                      {...register('sim_latency_max_ms', {
                        valueAsNumber: true,
                        min: { value: 0, message: 'Min 0' },
                      })}
                      className="h-8 font-mono"
                    />
                  </div>
                </div>

                {/* Outage windows */}
                <div className="space-y-1.5">
                  <FieldLabel>Daily outage windows (UTC)</FieldLabel>
                  <OutageWindowEditor windows={outageWindows} onChange={setOutageWindows} />
                </div>
              </div>
            )}
          </div>

          {apiError && (
            <p className="text-xs text-danger bg-danger-subtle rounded px-3 py-2">{apiError}</p>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" size="sm" disabled={isSubmitting}>
              {isSubmitting ? 'Saving…' : isEdit ? 'Save changes' : 'Create endpoint'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// ---- Delete confirm dialog ----

function DeleteDialog({
  endpoint,
  open,
  onClose,
}: {
  endpoint: Endpoint
  open: boolean
  onClose: () => void
}) {
  const del = useDeleteEndpoint()
  const [error, setError] = useState<string | null>(null)

  const handleDelete = async () => {
    setError(null)
    try {
      await del.mutateAsync(endpoint.id)
      onClose()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Delete failed')
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete endpoint</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground py-2">
          This will permanently delete{' '}
          <span className="font-medium text-foreground">{endpoint.name}</span> and all its history,
          incidents, and postmortems. This cannot be undone.
        </p>
        {error && <p className="text-xs text-danger">{error}</p>}
        <DialogFooter>
          <Button variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            size="sm"
            onClick={handleDelete}
            disabled={del.isPending}
          >
            {del.isPending ? 'Deleting…' : 'Delete'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ---- Endpoints page ----

type DialogState =
  | { type: 'create' }
  | { type: 'edit'; endpoint: Endpoint }
  | { type: 'delete'; endpoint: Endpoint }
  | null

export default function EndpointsPage() {
  const { data: endpoints = [], isLoading } = useEndpoints()
  const enableEndpoint = useEnableEndpoint()
  const disableEndpoint = useDisableEndpoint()
  const [dialog, setDialog] = useState<DialogState>(null)
  const [dialogKey, setDialogKey] = useState(0)

  const openDialog = (state: DialogState) => {
    setDialogKey((k) => k + 1)
    setDialog(state)
  }

  const toggleEnabled = (ep: Endpoint) => {
    if (ep.enabled) disableEndpoint.mutate(ep.id)
    else enableEndpoint.mutate(ep.id)
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-lg font-semibold">Endpoints</h1>
          <p className="text-xs text-muted-foreground mt-0.5 font-mono">
            {endpoints.length} registered
          </p>
        </div>
        <Button size="sm" onClick={() => openDialog({ type: 'create' })}>
          New endpoint
        </Button>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-12 bg-card border border-border rounded-lg animate-pulse" />
          ))}
        </div>
      ) : endpoints.length === 0 ? (
        <div className="text-center py-20 text-muted-foreground">
          <p className="text-sm">No endpoints yet.</p>
          <Button
            size="sm"
            variant="outline"
            className="mt-3"
            onClick={() => openDialog({ type: 'create' })}
          >
            Create your first endpoint
          </Button>
        </div>
      ) : (
        <div className="border border-border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/30 text-xs text-muted-foreground font-mono">
                <th className="text-left px-4 py-2.5 font-medium">Name</th>
                <th className="text-left px-4 py-2.5 font-medium hidden md:table-cell">URL</th>
                <th className="text-left px-4 py-2.5 font-medium">Status</th>
                <th className="text-left px-4 py-2.5 font-medium hidden sm:table-cell">
                  Interval
                </th>
                <th className="text-left px-4 py-2.5 font-medium hidden lg:table-cell">
                  Last check
                </th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {endpoints.map((ep) => (
                <tr
                  key={ep.id}
                  className="hover:bg-muted/20 transition-colors group"
                >
                  <td className="px-4 py-3">
                    <Link
                      href={`/endpoints/${ep.id}`}
                      className="font-medium hover:text-primary hover:underline"
                    >
                      {ep.name}
                    </Link>
                  </td>
                  <td className="px-4 py-3 hidden md:table-cell">
                    <span className="font-mono text-xs text-muted-foreground truncate max-w-xs block">
                      {ep.url}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      {ep.current_streak_outcome === 'success' && (
                        <span className="inline-flex items-center gap-1 text-xs font-mono text-success">
                          <span className="w-1.5 h-1.5 rounded-full bg-success inline-block" />
                          Up
                        </span>
                      )}
                      {ep.current_streak_outcome === 'failure' && (
                        <span className="inline-flex items-center gap-1 text-xs font-mono text-danger">
                          <span className="w-1.5 h-1.5 rounded-full bg-danger inline-block" />
                          Down
                        </span>
                      )}
                      {ep.current_streak_outcome === null && (
                        <span className="text-xs font-mono text-muted-foreground">Unknown</span>
                      )}
                      {!ep.enabled && (
                        <Badge
                          variant="outline"
                          className="text-[10px] px-1 py-0 font-mono"
                        >
                          Disabled
                        </Badge>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 hidden sm:table-cell">
                    <span className="font-mono text-xs text-muted-foreground">
                      {formatInterval(ep.check_interval_seconds)}
                    </span>
                  </td>
                  <td className="px-4 py-3 hidden lg:table-cell">
                    <span className="font-mono text-xs text-muted-foreground">
                      {ep.next_due_at ? formatRelativeTime(ep.next_due_at) : '—'}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      <Button
                        variant="ghost"
                        size="xs"
                        onClick={() => toggleEnabled(ep)}
                        className="text-xs font-mono text-muted-foreground"
                      >
                        {ep.enabled ? 'Disable' : 'Enable'}
                      </Button>
                      <Button
                        variant="ghost"
                        size="xs"
                        onClick={() => openDialog({ type: 'edit', endpoint: ep })}
                      >
                        Edit
                      </Button>
                      <Button
                        variant="ghost"
                        size="xs"
                        onClick={() => openDialog({ type: 'delete', endpoint: ep })}
                        className="text-danger hover:text-danger hover:bg-danger-subtle"
                      >
                        Delete
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Dialogs */}
      <EndpointDialog
        key={dialogKey}
        endpoint={dialog?.type === 'edit' ? dialog.endpoint : undefined}
        open={dialog?.type === 'create' || dialog?.type === 'edit'}
        onClose={() => setDialog(null)}
      />
      {dialog?.type === 'delete' && (
        <DeleteDialog
          endpoint={dialog.endpoint}
          open
          onClose={() => setDialog(null)}
        />
      )}
    </div>
  )
}
