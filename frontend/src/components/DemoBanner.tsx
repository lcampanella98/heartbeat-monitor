'use client'

import { useSystemStatus } from '@/lib/queries'

export function DemoBanner() {
  const { data } = useSystemStatus()

  if (!data) return null
  if (data.check_source !== 'simulated' && data.email_sink !== 'log') return null

  const modes: string[] = []
  if (data.check_source === 'simulated') modes.push('simulated checks (no real HTTP requests)')
  if (data.email_sink === 'log') modes.push('log email sink (no outbound email)')

  return (
    <div className="bg-amber-50 border-b border-amber-200 px-4 py-2 text-sm text-amber-900">
      Demo mode active: {modes.join('; ')}.
    </div>
  )
}
