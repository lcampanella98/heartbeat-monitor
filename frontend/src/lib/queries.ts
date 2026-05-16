import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import type {
  CheckResult,
  Endpoint,
  EndpointCreate,
  EndpointUpdate,
  EmailRecipient,
  HistoryBin,
  Incident,
  SentNotification,
  StorageStats,
  SystemStatus,
  UptimePercentages,
} from '@/types'

// staleTime defaults — pages override refetchInterval as needed
const STALE_30S = 30_000
const STALE_60S = 60_000

// ---- System ----

export function useSystemStatus() {
  return useQuery({
    queryKey: ['system-status'],
    queryFn: () => api.get<SystemStatus>('/system/status'),
    staleTime: STALE_60S,
  })
}

// ---- Endpoints ----

export function useEndpoints() {
  return useQuery({
    queryKey: ['endpoints'],
    queryFn: () => api.get<Endpoint[]>('/endpoints'),
    staleTime: STALE_30S,
  })
}

export function useEndpoint(id: number) {
  return useQuery({
    queryKey: ['endpoints', id],
    queryFn: () => api.get<Endpoint>(`/endpoints/${id}`),
    staleTime: STALE_30S,
  })
}

export function useCreateEndpoint() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: EndpointCreate) => api.post<Endpoint>('/endpoints', data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['endpoints'] }),
  })
}

export function useUpdateEndpoint(id: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: EndpointUpdate) => api.put<Endpoint>(`/endpoints/${id}`, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['endpoints'] })
      qc.invalidateQueries({ queryKey: ['endpoints', id] })
    },
  })
}

export function useDeleteEndpoint() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete(`/endpoints/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['endpoints'] }),
  })
}

export function useEnableEndpoint() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.post<Endpoint>(`/endpoints/${id}/enable`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['endpoints'] }),
  })
}

export function useDisableEndpoint() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.post<Endpoint>(`/endpoints/${id}/disable`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['endpoints'] }),
  })
}

export function useRecentChecks(endpointId: number, limit = 60) {
  return useQuery({
    queryKey: ['recent-checks', endpointId, limit],
    queryFn: () =>
      api.get<CheckResult[]>(`/endpoints/${endpointId}/recent-checks?limit=${limit}`),
    staleTime: STALE_30S,
  })
}

export function useEndpointHistory(
  endpointId: number,
  range: '1h' | '1d' | '7d' | '30d' | '90d' | '1y',
) {
  return useQuery({
    queryKey: ['history', endpointId, range],
    queryFn: () =>
      api.get<HistoryBin[]>(`/endpoints/${endpointId}/history?range=${range}`),
    staleTime: STALE_60S,
  })
}

export function useEndpointUptime(endpointId: number) {
  return useQuery({
    queryKey: ['uptime', endpointId],
    queryFn: () => api.get<UptimePercentages>(`/endpoints/${endpointId}/uptime`),
    staleTime: STALE_60S,
  })
}

// ---- Incidents ----

export function useIncidents(params?: {
  state?: 'active' | 'closed' | 'all'
  endpoint_id?: number
}) {
  const qs = new URLSearchParams()
  if (params?.state) qs.set('state', params.state)
  if (params?.endpoint_id != null) qs.set('endpoint_id', String(params.endpoint_id))
  const queryString = qs.toString()

  return useQuery({
    queryKey: ['incidents', params],
    queryFn: () => api.get<Incident[]>(`/incidents${queryString ? `?${queryString}` : ''}`),
    staleTime: STALE_30S,
  })
}

export function useIncident(id: number) {
  return useQuery({
    queryKey: ['incidents', id],
    queryFn: () => api.get<Incident>(`/incidents/${id}`),
    staleTime: STALE_30S,
  })
}

export function useGeneratePostmortem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (incidentId: number) =>
      api.post<{ content: string }>(`/incidents/${incidentId}/postmortem/generate`),
    onSuccess: (_data, incidentId) => {
      qc.invalidateQueries({ queryKey: ['incidents', incidentId] })
    },
  })
}

export function useUpdatePostmortem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ incidentId, content }: { incidentId: number; content: string }) =>
      api.put<void>(`/incidents/${incidentId}/postmortem`, { content }),
    onSuccess: (_data, { incidentId }) => {
      qc.invalidateQueries({ queryKey: ['incidents', incidentId] })
    },
  })
}

// ---- Recipients ----

export function useRecipients() {
  return useQuery({
    queryKey: ['recipients'],
    queryFn: () => api.get<EmailRecipient[]>('/recipients'),
    staleTime: STALE_60S,
  })
}

export function useAddRecipient() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (address: string) => api.post<EmailRecipient>('/recipients', { address }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['recipients'] }),
  })
}

export function useDeleteRecipient() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete(`/recipients/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['recipients'] }),
  })
}

// ---- Notifications ----

export function useNotifications(beforeId?: number, limit = 100) {
  const qs = new URLSearchParams({ limit: String(limit) })
  if (beforeId != null) qs.set('before_id', String(beforeId))

  return useQuery({
    queryKey: ['notifications', beforeId, limit],
    queryFn: () => api.get<SentNotification[]>(`/notifications?${qs.toString()}`),
    staleTime: STALE_30S,
  })
}

// ---- Storage ----

export function useStorageStats() {
  return useQuery({
    queryKey: ['storage-stats'],
    queryFn: () => api.get<StorageStats>('/storage/stats'),
    staleTime: STALE_30S,
  })
}

export function useRunRollup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<StorageStats>('/storage/rollup-now'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['storage-stats'] }),
  })
}
