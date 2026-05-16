export type StreakOutcome = 'success' | 'failure'
export type ErrorCategory = 'timeout' | 'connection_refused' | 'dns' | 'tls' | 'non_2xx' | 'other'
export type NotificationKind = 'incident_opened' | 'incident_closed'

export interface SimOutageWindow {
  start: string
  end: string
}

export interface Endpoint {
  id: number
  user_id: number
  name: string
  url: string
  enabled: boolean
  check_interval_seconds: 30 | 60 | 300 | 900
  timeout_seconds: number
  next_due_at: string | null
  current_streak_outcome: StreakOutcome | null
  current_streak_count: number
  streak_started_at: string | null
  sim_failure_rate: number
  sim_latency_min_ms: number
  sim_latency_max_ms: number
  sim_outage_windows: SimOutageWindow[]
  created_at: string
  updated_at: string
}

export interface EndpointCreate {
  name: string
  url: string
  check_interval_seconds: 30 | 60 | 300 | 900
  timeout_seconds?: number
  enabled?: boolean
  sim_failure_rate?: number
  sim_latency_min_ms?: number
  sim_latency_max_ms?: number
  sim_outage_windows?: SimOutageWindow[]
}

export interface EndpointUpdate {
  name?: string
  url?: string
  check_interval_seconds?: 30 | 60 | 300 | 900
  timeout_seconds?: number
  enabled?: boolean
  sim_failure_rate?: number
  sim_latency_min_ms?: number
  sim_latency_max_ms?: number
  sim_outage_windows?: SimOutageWindow[] | null
}

export interface CheckResult {
  id: number
  endpoint_id: number
  checked_at: string
  outcome: StreakOutcome
  latency_ms: number
  status_code: number | null
  error_category: ErrorCategory | null
  error_message: string | null
}

export interface Postmortem {
  content: string | null
  generated_at: string | null
  edited_at: string | null
}

export interface Incident {
  id: number
  endpoint_id: number
  started_at: string
  ended_at: string | null
  duration_seconds: number | null
  frozen_timeline: CheckResult[] | null
  created_at: string
  postmortem: Postmortem | null
}

export interface EmailRecipient {
  id: number
  address: string
  created_at: string
}

export interface SentNotification {
  id: number
  kind: NotificationKind
  incident_id: number
  subject: string
  body: string
  recipients: string[]
  sent_at: string
}

export interface HistoryBin {
  bucket_start: string
  source: 'raw' | 'hourly' | 'daily'
  total_checks: number
  successful_checks: number
  failed_checks: number
  uptime_pct: number
}

export interface UptimePercentages {
  h24: number
  d7: number
  d30: number
}

export interface StorageStats {
  raw_count: number
  hourly_count: number
  daily_count: number
  raw_retention_days: number
  hourly_retention_days: number
  daily_retention_days: number | null
  last_rollup_at: string | null
  next_rollup_at: string | null
}

export interface SystemStatus {
  check_source: 'real' | 'simulated'
  email_sink: 'smtp' | 'log'
  smtp_from: string | null
  n: number
  m: number
}
