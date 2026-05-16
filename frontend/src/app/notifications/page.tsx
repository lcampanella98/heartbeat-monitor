'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useNotifications } from '@/lib/queries'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { formatTimestamp } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { SentNotification } from '@/types'

function KindBadge({ kind }: { kind: SentNotification['kind'] }) {
  if (kind === 'incident_opened')
    return (
      <Badge className="bg-danger/10 text-danger border-danger/20 font-mono text-[10px] px-1.5">
        opened
      </Badge>
    )
  return (
    <Badge className="bg-success/10 text-success border-success/20 font-mono text-[10px] px-1.5">
      closed
    </Badge>
  )
}

function NotificationRow({ notification }: { notification: SentNotification }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="border-b border-border last:border-0">
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="w-full flex items-start gap-3 px-4 py-3 hover:bg-muted/20 transition-colors text-left"
      >
        <span
          className={cn(
            'text-muted-foreground/40 font-mono text-xs mt-0.5 transition-transform shrink-0',
            expanded && 'rotate-90',
          )}
        >
          ▶
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <KindBadge kind={notification.kind} />
            <span className="text-sm font-medium truncate">{notification.subject}</span>
          </div>
          <div className="flex items-center gap-3 mt-0.5">
            <span className="text-xs font-mono text-muted-foreground">
              {formatTimestamp(notification.sent_at)}
            </span>
            <span className="text-xs text-muted-foreground/50 font-mono">
              {notification.recipients.length}{' '}
              recipient{notification.recipients.length !== 1 ? 's' : ''}
            </span>
            <Link
              href={`/incidents/${notification.incident_id}`}
              className="text-xs text-primary hover:underline font-mono"
              onClick={(e) => e.stopPropagation()}
            >
              Incident #{notification.incident_id}
            </Link>
          </div>
        </div>
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-3 border-t border-border/50 mt-0 bg-muted/10">
          <div className="pt-3">
            <p className="text-xs font-mono text-muted-foreground mb-1">Recipients</p>
            <div className="flex flex-wrap gap-1">
              {notification.recipients.map((r) => (
                <span
                  key={r}
                  className="inline-block text-xs font-mono bg-muted px-2 py-0.5 rounded"
                >
                  {r}
                </span>
              ))}
            </div>
          </div>
          <div>
            <p className="text-xs font-mono text-muted-foreground mb-1">Body</p>
            <pre className="text-xs font-mono whitespace-pre-wrap bg-muted/30 rounded p-3 text-foreground/80 overflow-auto max-h-48">
              {notification.body}
            </pre>
          </div>
        </div>
      )}
    </div>
  )
}

export default function NotificationsPage() {
  // extra pages fetched via "load more"
  const [extra, setExtra] = useState<SentNotification[]>([])
  const [hasMore, setHasMore] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)

  const { data: initial = [], isLoading } = useNotifications(undefined, 100)

  const items = [...initial, ...extra]

  const loadMore = async () => {
    const oldest = items[items.length - 1]
    if (!oldest || loadingMore) return
    setLoadingMore(true)
    try {
      const more = await api.get<SentNotification[]>(
        `/notifications?limit=100&before_id=${oldest.id}`,
      )
      setExtra((prev) => [...prev, ...more])
      setHasMore(more.length === 100)
    } finally {
      setLoadingMore(false)
    }
  }

  // Show "load more" only if first page was full
  const showLoadMore = hasMore && initial.length === 100

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-lg font-semibold">Notifications</h1>
        <p className="text-xs text-muted-foreground mt-0.5 font-mono">
          Sent alerts (ring buffer, last 1000)
        </p>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-14 bg-card border border-border rounded-lg animate-pulse" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="text-center py-20 text-muted-foreground">
          <p className="text-sm">No notifications yet.</p>
          <p className="text-xs mt-1 text-muted-foreground/60">
            Notifications appear here when incidents open or close.
          </p>
        </div>
      ) : (
        <>
          <div className="border border-border rounded-lg overflow-hidden">
            {items.map((n) => (
              <NotificationRow key={n.id} notification={n} />
            ))}
          </div>

          {showLoadMore && (
            <div className="mt-4 flex justify-center">
              <Button
                variant="outline"
                size="sm"
                onClick={loadMore}
                disabled={loadingMore}
                className="text-xs font-mono"
              >
                {loadingMore ? 'Loading…' : 'Load more'}
              </Button>
            </div>
          )}

          {!hasMore && items.length > 0 && (
            <p className="text-center text-xs text-muted-foreground/40 font-mono mt-4">
              End of notifications
            </p>
          )}
        </>
      )}
    </div>
  )
}
