'use client'

import { useState } from 'react'
import { cn } from '@/lib/utils'
import { formatTimestamp } from '@/lib/format'
import type { CheckResult } from '@/types'

interface Props {
  checks: CheckResult[]
  maxCount?: number
}

export function RecentCheckStrip({ checks, maxCount = 60 }: Props) {
  const [hovered, setHovered] = useState<CheckResult | null>(null)

  const ticks = Array.from({ length: maxCount }, (_, i) => {
    const idx = checks.length - maxCount + i
    return idx >= 0 ? checks[idx] : null
  })

  return (
    <div className="relative">
      <div className="flex items-center gap-px h-5">
        {ticks.map((check, i) => (
          <div
            key={i}
            className={cn(
              'w-1 h-5 rounded-sm transition-opacity cursor-default',
              !check && 'bg-muted/50',
              check?.outcome === 'success' && 'bg-success hover:opacity-75',
              check?.outcome === 'failure' && 'bg-danger hover:opacity-75',
            )}
            onMouseEnter={() => setHovered(check)}
            onMouseLeave={() => setHovered(null)}
          />
        ))}
      </div>
      {hovered && (
        <div className="absolute bottom-7 left-0 z-20 bg-popover border border-border rounded-lg px-3 py-2 text-xs shadow-xl whitespace-nowrap pointer-events-none">
          <p className="font-mono text-muted-foreground mb-0.5">
            {formatTimestamp(hovered.checked_at)}
          </p>
          <p
            className={cn(
              'font-medium',
              hovered.outcome === 'success' ? 'text-success' : 'text-danger',
            )}
          >
            {hovered.outcome} &mdash;{' '}
            <span className="font-mono">{hovered.latency_ms}ms</span>
          </p>
          {hovered.error_message && (
            <p className="text-muted-foreground mt-0.5 max-w-52 truncate">
              {hovered.error_message}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
