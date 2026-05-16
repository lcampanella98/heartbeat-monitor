'use client'

import { useState } from 'react'
import {
  useRecipients,
  useAddRecipient,
  useDeleteRecipient,
  useStorageStats,
  useRunRollup,
  useSystemStatus,
} from '@/lib/queries'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { formatTimestamp } from '@/lib/format'

// ---- Section wrapper ----

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-card border border-border rounded-lg overflow-hidden">
      <div className="px-4 py-3 border-b border-border">
        <h2 className="text-sm font-semibold">{title}</h2>
      </div>
      <div className="p-4">{children}</div>
    </div>
  )
}

// ---- Mode badge ----

function ModeBadge({ label, value, active }: { label: string; value: string; active?: boolean }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-border/50 last:border-0">
      <span className="text-xs text-muted-foreground font-mono">{label}</span>
      <Badge
        variant={active ? 'default' : 'outline'}
        className="font-mono text-[10px] px-1.5"
      >
        {value}
      </Badge>
    </div>
  )
}

// ---- Recipients editor ----

function RecipientsSection() {
  const { data: recipients = [], isLoading } = useRecipients()
  const addRecipient = useAddRecipient()
  const deleteRecipient = useDeleteRecipient()
  const [newAddress, setNewAddress] = useState('')
  const [error, setError] = useState<string | null>(null)

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = newAddress.trim()
    if (!trimmed) return
    setError(null)
    try {
      await addRecipient.mutateAsync(trimmed)
      setNewAddress('')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to add recipient')
    }
  }

  return (
    <Section title="Email recipients">
      {isLoading ? (
        <div className="h-8 bg-muted animate-pulse rounded" />
      ) : (
        <div className="space-y-3">
          {recipients.length > 0 && (
            <div className="space-y-1">
              {recipients.map((r) => (
                <div
                  key={r.id}
                  className="flex items-center justify-between py-1.5 px-2 rounded hover:bg-muted/30 group"
                >
                  <span className="text-sm font-mono">{r.address}</span>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    onClick={() => deleteRecipient.mutate(r.id)}
                    className="opacity-0 group-hover:opacity-100 text-danger hover:text-danger hover:bg-danger-subtle"
                  >
                    &times;
                  </Button>
                </div>
              ))}
            </div>
          )}

          <form onSubmit={handleAdd} className="flex gap-2">
            <Input
              type="email"
              value={newAddress}
              onChange={(e) => setNewAddress(e.target.value)}
              placeholder="email@example.com"
              className="h-8 text-sm font-mono flex-1"
            />
            <Button
              type="submit"
              size="sm"
              disabled={addRecipient.isPending || !newAddress.trim()}
            >
              Add
            </Button>
          </form>

          {error && <p className="text-xs text-danger">{error}</p>}

          {recipients.length === 0 && (
            <p className="text-xs text-muted-foreground">
              No recipients. Add email addresses to receive incident alerts.
            </p>
          )}
        </div>
      )}
    </Section>
  )
}

// ---- Storage panel ----

function StorageSection() {
  const { data: stats, isLoading } = useStorageStats()
  const runRollup = useRunRollup()
  const [rollupError, setRollupError] = useState<string | null>(null)

  const handleRollup = async () => {
    setRollupError(null)
    try {
      await runRollup.mutateAsync()
    } catch (err: unknown) {
      setRollupError(err instanceof Error ? err.message : 'Rollup failed')
    }
  }

  return (
    <Section title="Storage">
      {isLoading ? (
        <div className="h-32 bg-muted animate-pulse rounded" />
      ) : !stats ? (
        <p className="text-xs text-muted-foreground">Failed to load storage stats.</p>
      ) : (
        <div className="space-y-4">
          {/* Tier counts */}
          <div className="grid grid-cols-3 gap-3">
            {[
              {
                label: 'Raw checks',
                count: stats.raw_count,
                retention: `${stats.raw_retention_days}d`,
              },
              {
                label: 'Hourly rollups',
                count: stats.hourly_count,
                retention: `${stats.hourly_retention_days}d`,
              },
              {
                label: 'Daily rollups',
                count: stats.daily_count,
                retention: stats.daily_retention_days != null
                  ? `${stats.daily_retention_days}d`
                  : 'indefinite',
              },
            ].map(({ label, count, retention }) => (
              <div key={label} className="bg-muted/30 rounded-lg p-3">
                <p className="text-xs text-muted-foreground mb-1">{label}</p>
                <p className="text-lg font-mono font-semibold">
                  {count.toLocaleString()}
                </p>
                <p className="text-xs font-mono text-muted-foreground/60 mt-0.5">
                  retention: {retention}
                </p>
              </div>
            ))}
          </div>

          {/* Rollup timing */}
          <div className="space-y-1.5 text-xs font-mono">
            <div className="flex items-center justify-between text-muted-foreground">
              <span>Last rollup</span>
              <span>{stats.last_rollup_at ? formatTimestamp(stats.last_rollup_at) : '—'}</span>
            </div>
            <div className="flex items-center justify-between text-muted-foreground">
              <span>Next rollup</span>
              <span>{stats.next_rollup_at ? formatTimestamp(stats.next_rollup_at) : '—'}</span>
            </div>
          </div>

          {rollupError && (
            <p className="text-xs text-danger">{rollupError}</p>
          )}

          <Button
            variant="outline"
            size="sm"
            onClick={handleRollup}
            disabled={runRollup.isPending}
            className="text-xs font-mono"
          >
            {runRollup.isPending ? 'Running rollup…' : 'Run rollup now'}
          </Button>
        </div>
      )}
    </Section>
  )
}

// ---- System info ----

function SystemSection() {
  const { data: status, isLoading } = useSystemStatus()

  return (
    <Section title="System info">
      {isLoading ? (
        <div className="h-24 bg-muted animate-pulse rounded" />
      ) : !status ? (
        <p className="text-xs text-muted-foreground">Failed to load system status.</p>
      ) : (
        <div>
          <ModeBadge
            label="Check source"
            value={status.check_source}
            active={status.check_source === 'real'}
          />
          <ModeBadge
            label="Email sink"
            value={status.email_sink}
            active={status.email_sink === 'smtp'}
          />
          <ModeBadge
            label="SMTP from"
            value={status.smtp_from ?? '(not configured)'}
          />
          <ModeBadge label="Incident open threshold (N)" value={String(status.n)} />
          <ModeBadge label="Incident close threshold (M)" value={String(status.m)} />
        </div>
      )}
    </Section>
  )
}

// ---- Page ----

export default function SettingsPage() {
  return (
    <div className="p-6 max-w-2xl">
      <div className="mb-6">
        <h1 className="text-lg font-semibold">Settings</h1>
        <p className="text-xs text-muted-foreground mt-0.5 font-mono">
          Recipients, storage, and runtime configuration
        </p>
      </div>

      <div className="space-y-6">
        <RecipientsSection />
        <StorageSection />
        <SystemSection />
      </div>
    </div>
  )
}
