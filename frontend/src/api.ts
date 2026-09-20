export type HealthState = 'healthy' | 'degraded' | 'unhealthy' | 'unknown'
export type Severity = 'low' | 'medium' | 'high' | 'critical'
export type IncidentState = 'open' | 'recovering' | 'resolved'
export type InvestigationState = 'queued' | 'running' | 'succeeded' | 'failed'
export type QualityState = 'complete' | 'partial' | 'insufficient' | 'unknown'

export type ServiceKey = { service_id: string; namespace: string; environment: string; name: string }
export type TimeRange = { start: string; end: string }
export type Freshness = { generated_at: string; latest_source_at: string | null; age_seconds: number | null; state: 'fresh' | 'stale' | 'unknown' | 'not_applicable' }
export type Coverage = { status: 'complete' | 'partial' | 'unknown'; reasons: string[]; omitted_count: number | null; message: string | null }
export type Envelope<T> = { result: T; request_id: string; freshness: Freshness; coverage: Coverage }
export type Page<T> = { items: T[]; next_cursor: string | null; has_more: boolean }

export type HealthResponse = { status: 'ok'; service: 'aiops-api'; version: string; checked_at: string }
export type ReadyResponse = { status: 'ready' | 'not_ready'; checked_at: string; checks: Array<{ name: string; state: 'pass' | 'fail'; reason_code: string | null; checked_at: string }> }

export type MetricBucket = {
  bucket_id: string; service: ServiceKey; window: TimeRange; request_count: number; error_count: number
  error_rate: number | null; latency_p95_ms: number | null; quality_status: QualityState
  quality_reasons: string[]; eligible_for_detection: boolean; finalized_at: string | null
}
export type ServiceHealth = { service: ServiceKey; state: HealthState; reason: string; assessed_at: string; latest_bucket_end: string | null; telemetry_age_seconds: number | null; active_incident_ids: string[]; quality_status: QualityState; quality_reasons: string[] }
export type ServiceSummary = { service: ServiceKey; health: ServiceHealth; last_seen_at: string | null; active_incident_count: number }
export type IncidentSummary = { incident_id: string; primary_service: ServiceKey; feature: 'latency_p95_ms' | 'error_rate'; state: IncidentState; severity: Severity; peak_severity: Severity; detected_at: string; first_affected_at: string; updated_at: string; evidence_status: string; latest_investigation_id: string | null; fixture_source: boolean }
export type ComponentStatus = { name: string; state: 'healthy' | 'degraded' | 'unavailable' | 'unknown'; checked_at: string; reason: string | null }
export type Overview = { overall_health: HealthState; service_counts: Record<HealthState, number>; active_incident_count: number; recent_incidents: IncidentSummary[]; components: ComponentStatus[] }
export type ServiceDetail = { summary: ServiceSummary; instances: unknown[]; detectors: unknown[]; latest_bucket: MetricBucket | null; dependency_count: number | null }
export type MetricsResponse = { service: ServiceKey; window: TimeRange; interval_seconds: 60; requested_features: Array<'latency_p95_ms' | 'error_rate'>; buckets: Page<MetricBucket>; native_points: unknown[] }
export type DependencyEdge = { edge_id: string; source_service: ServiceKey; target_service: ServiceKey; window_start: string; window_end: string; observed_trace_count: number | null; sample_trace_ids: string[]; observed_at: string; source_kind: string }
export type DependenciesResponse = { service: ServiceKey; window: TimeRange; edges: Page<DependencyEdge> }

export type RecoveryBaseline = { window: TimeRange; latency_p95_median_ms: number; error_rate_median: number }
export type Incident = IncidentSummary & { affected_services: ServiceKey[]; severity_reason: string; opened_by_anomaly_id: string; anomaly_count: number; recent_anomaly_ids: string[]; related_incidents: unknown[]; last_affected_at: string; recovering_since: string | null; resolved_at: string | null; recovery_baseline: RecoveryBaseline | null; healthy_bucket_streak: number; latest_evidence_bundle_id: string | null; evidence_version: number; policy_version: string }
export type TimelineEntry = { entry_id: string; occurred_at: string; kind: string; summary: string; evidence_ids: string[]; related_investigation_id: string | null }
export type EvidenceBundle = { bundle_id: string; incident_id: string; version: number; window: TimeRange; evidence_ids: string[]; quality_status: QualityState; quality_reasons: string[]; total_bytes: number; created_at: string }
export type EvidenceItem = { evidence_id: string; evidence_type: 'anomaly_result' | 'metric_bucket' | 'log_record' | 'span' | 'trace' | 'dependency_edge'; service: ServiceKey; window: TimeRange; summary: string; quality_status: QualityState; quality_reasons: string[]; redaction_status: string; snapshot: Record<string, unknown>; created_at: string }
export type IncidentDetail = { incident: Incident; evidence_bundle: EvidenceBundle | null; timeline: Page<TimelineEntry>; latest_investigation: InvestigationView | null }
export type EvidenceResponse = { incident_id: string; bundle: EvidenceBundle; items: Page<EvidenceItem> }

export type EvidenceClaim = { statement: string; evidence_ids: string[] }
export type SuggestedAction = { instruction: string; rationale: EvidenceClaim; executed: false }
export type InvestigationReport = { summary: EvidenceClaim; affected_services: ServiceKey[]; affected_service_claims: EvidenceClaim[]; suspected_root_service: ServiceKey | null; root_service_claim: EvidenceClaim | null; primary_hypothesis: EvidenceClaim | null; supporting_evidence_ids: string[]; contradicting_evidence: EvidenceClaim[]; alternative_explanations: EvidenceClaim[]; confidence: 'low' | 'medium' | 'high'; confidence_rationale: string; recommended_next_checks: SuggestedAction[]; suggested_remediation: SuggestedAction[]; missing_evidence: string[]; limitations: string[]; completion_status: 'complete' | 'partial' | 'insufficient_evidence'; generated_at: string }
export type InvestigationView = { investigation_id: string; incident_id: string; evidence_version: number; state: InvestigationState; attempt_count: number; created_at: string; started_at: string | null; finished_at: string | null; report: InvestigationReport | null; failure: { code: string; message: string; retryable: boolean } | null; additional_evidence: EvidenceItem[]; fixture_source: boolean }
export type InvestigationAccepted = { investigation_id: string; state: InvestigationState; incident_id: string; evidence_version: number; created_at: string }

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try { response = await fetch(`${API_BASE}${path}`, { ...init, headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...init?.headers } }) }
  catch { throw new ApiError(0, 'The AIOps API is unavailable.') }
  if (!response.ok) {
    let message = `API request failed (${response.status})`
    try { const body = await response.json() as { detail?: string }; message = body.detail ?? message } catch { /* safe fallback */ }
    throw new ApiError(response.status, message)
  }
  return response.json() as Promise<T>
}

export const api = {
  health: () => request<HealthResponse>('/health'),
  ready: () => request<ReadyResponse>('/ready'),
  overview: () => request<Envelope<Overview>>('/api/v1/overview'),
  services: () => request<Envelope<Page<ServiceSummary>>>('/api/v1/services'),
  service: (id: string) => request<Envelope<ServiceDetail>>(`/api/v1/services/${id}`),
  metrics: (id: string) => request<Envelope<MetricsResponse>>(`/api/v1/services/${id}/metrics`),
  dependencies: (id: string) => request<Envelope<DependenciesResponse>>(`/api/v1/services/${id}/dependencies`),
  incidents: (query = '') => request<Envelope<Page<IncidentSummary>>>(`/api/v1/incidents${query}`),
  incident: (id: string) => request<Envelope<IncidentDetail>>(`/api/v1/incidents/${id}`),
  evidence: (id: string) => request<Envelope<EvidenceResponse>>(`/api/v1/incidents/${id}/evidence?limit=50`),
  investigation: (id: string) => request<Envelope<InvestigationView>>(`/api/v1/investigations/${id}`),
  investigate: (id: string, key: string) => request<Envelope<InvestigationAccepted>>(`/api/v1/incidents/${id}/investigate`, { method: 'POST', headers: { 'Idempotency-Key': key }, body: '{}' }),
}
