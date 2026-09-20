import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { App } from './App'

const svcId = `svc_${'a'.repeat(64)}`
const incidentId = `incident_${'b'.repeat(64)}`
const evidenceId = `ev_${'c'.repeat(64)}`
const investigationId = `inv_${'d'.repeat(64)}`
const service = { service_id: svcId, namespace: 'demo-shop', environment: 'development', name: 'payment-service' }
const bucket = { bucket_id: `bucket_${'e'.repeat(64)}`, service, window: { start: '2026-09-20T12:00:00Z', end: '2026-09-20T12:01:00Z' }, request_count: 100, error_count: 20, error_rate: .2, latency_p95_ms: 750, quality_status: 'complete', quality_reasons: [], eligible_for_detection: true, finalized_at: '2026-09-20T12:03:00Z' }
const health = { service, state: 'unknown', reason: 'Detector readiness is not exposed; healthy cannot be inferred', assessed_at: '2026-09-20T12:04:00Z', latest_bucket_end: bucket.window.end, telemetry_age_seconds: 420, active_incident_ids: [incidentId], quality_status: 'unknown', quality_reasons: ['detector_unready'] }
const incident = { incident_id: incidentId, primary_service: service, affected_services: [service], feature: 'error_rate', state: 'open', severity: 'critical', peak_severity: 'critical', severity_reason: 'error_rate 0.20 >= 0.20', severity_bucket_ids: [bucket.bucket_id], opened_by_anomaly_id: `anomaly_${'f'.repeat(64)}`, anomaly_count: 1, recent_anomaly_ids: [`anomaly_${'f'.repeat(64)}`], related_incidents: [], first_affected_at: bucket.window.start, last_affected_at: bucket.window.end, detected_at: '2026-09-20T12:04:00Z', updated_at: '2026-09-20T12:05:00Z', recovering_since: null, resolved_at: null, recovery_baseline: { window: { start: '2026-09-20T11:30:00Z', end: '2026-09-20T12:00:00Z' }, latency_p95_median_ms: 12, error_rate_median: 0 }, healthy_bucket_streak: 0, latest_evidence_bundle_id: `bundle_${'1'.repeat(64)}`, evidence_version: 1, evidence_status: 'ready', latest_investigation_id: null, policy_version: '1.0.0', fixture_source: true }
const evidence = { evidence_id: evidenceId, evidence_type: 'metric_bucket', service, window: bucket.window, summary: 'Payment error rate reached 20 percent', quality_status: 'complete', quality_reasons: [], redaction_status: 'checked_clear', snapshot: bucket, created_at: '2026-09-20T12:04:00Z' }
const envelope = <T,>(result: T) => ({ result, request_id: '00000000-0000-4000-8000-000000000001', freshness: { generated_at: '2026-09-20T12:05:00Z', latest_source_at: null, age_seconds: null, state: 'not_applicable' }, coverage: { status: 'complete', reasons: [], omitted_count: null, message: null } })

function response(body: unknown, status = 200) { return Promise.resolve({ ok: status >= 200 && status < 300, status, json: async () => body } as Response) }

function baseFetch(investigation: unknown = null) {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/ready')) return response({ status: 'ready', checked_at: '2026-09-20T12:05:00Z', checks: [] })
    if (url.endsWith('/api/v1/overview')) return response(envelope({ overall_health: 'unknown', service_counts: { healthy: 0, degraded: 0, unhealthy: 0, unknown: 1 }, active_incident_count: 1, recent_incidents: [incident], components: [{ name: 'detectors', state: 'unknown', checked_at: '2026-09-20T12:05:00Z', reason: 'Public detector status unavailable' }] }))
    if (url.endsWith(`/api/v1/services/${svcId}`)) return response(envelope({ summary: { service, health, last_seen_at: bucket.window.end, active_incident_count: 1 }, instances: [], detectors: [], latest_bucket: bucket, dependency_count: null }))
    if (url.endsWith('/api/v1/services')) return response(envelope({ items: [{ service, health, last_seen_at: bucket.window.end, active_incident_count: 1 }], next_cursor: null, has_more: false }))
    if (url.includes('/evidence')) return response(envelope({ incident_id: incidentId, bundle: { bundle_id: incident.latest_evidence_bundle_id, incident_id: incidentId, version: 1, window: bucket.window, evidence_ids: [evidenceId], quality_status: 'complete', quality_reasons: [], total_bytes: 900, created_at: incident.detected_at }, items: { items: [evidence], next_cursor: null, has_more: false } }))
    if (url.endsWith(`/incidents/${incidentId}/investigate`) && init?.method === 'POST') return response(envelope({ investigation_id: investigationId, state: 'queued', incident_id: incidentId, evidence_version: 1, created_at: incident.detected_at }), 202)
    if (url.endsWith(`/investigations/${investigationId}`)) return response(envelope(investigation))
    if (url.endsWith(`/incidents/${incidentId}`)) return response(envelope({ incident, evidence_bundle: null, timeline: { items: [{ entry_id: `timeline_${'2'.repeat(64)}`, occurred_at: incident.detected_at, kind: 'detected', summary: 'Development fixture incident opened', evidence_ids: [evidenceId], related_investigation_id: null }], next_cursor: null, has_more: false }, latest_investigation: null }))
    if (url.includes('/api/v1/incidents')) return response(envelope({ items: [incident], next_cursor: null, has_more: false }))
    throw new Error(`Unhandled request ${url}`)
  })
}

beforeEach(() => window.history.replaceState({}, '', '/'))
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

test('overview renders actual state and never turns stale unknown telemetry healthy', async () => {
  vi.stubGlobal('fetch', baseFetch())
  render(<App />)
  expect(await screen.findByRole('heading', { name: 'System at a glance' })).toBeInTheDocument()
  expect(screen.getAllByText('unknown').length).toBeGreaterThan(0)
  expect(screen.getAllByText('7m ago')).toHaveLength(2)
  expect(screen.getByText('Detector readiness is not exposed; healthy cannot be inferred')).toBeInTheDocument()
})

test('unavailable API has an explicit failure state', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
  render(<App />)
  expect(await screen.findByRole('alert')).toHaveTextContent('AIOps API is unavailable')
})

test('incident list renders operational fields and fixture provenance', async () => {
  window.history.replaceState({}, '', '/incidents')
  vi.stubGlobal('fetch', baseFetch())
  render(<App />)
  expect(await screen.findByRole('heading', { name: 'Incidents', level: 1 })).toBeInTheDocument()
  expect(screen.getAllByText('payment-service')).toHaveLength(2)
  expect(screen.getByText('fixture')).toBeInTheDocument()
})

test('incident detail renders metric evidence, timeline, and expandable evidence', async () => {
  window.history.replaceState({}, '', `/incidents/${incidentId}`)
  vi.stubGlobal('fetch', baseFetch())
  render(<App />)
  expect(await screen.findByText('Development fixture — not produced by live RCF')).toBeInTheDocument()
  expect(screen.getAllByText('20.0%').length).toBeGreaterThan(0)
  fireEvent.click(screen.getByText('Payment error rate reached 20 percent'))
  expect(screen.getByText(evidenceId)).toBeInTheDocument()
})

test('investigation request transitions to the persisted queued state', async () => {
  window.history.replaceState({}, '', `/incidents/${incidentId}`)
  const queued = { investigation_id: investigationId, incident_id: incidentId, evidence_version: 1, state: 'queued', attempt_count: 0, created_at: incident.detected_at, started_at: null, finished_at: null, report: null, failure: null, additional_evidence: [], fixture_source: true }
  vi.stubGlobal('fetch', baseFetch(queued))
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: 'Investigate with AI' }))
  expect(await screen.findByText('Queued for analysis')).toBeInTheDocument()
})

test('succeeded report renders citations and citation navigation opens stored evidence', async () => {
  window.history.replaceState({}, '', `/incidents/${incidentId}`)
  const claim = { statement: 'Errors rose in the triggering minute.', evidence_ids: [evidenceId] }
  const succeeded = { investigation_id: investigationId, incident_id: incidentId, evidence_version: 1, state: 'succeeded', attempt_count: 1, created_at: incident.detected_at, started_at: incident.detected_at, finished_at: incident.updated_at, report: { summary: claim, affected_services: [service], affected_service_claims: [claim], suspected_root_service: null, root_service_claim: null, primary_hypothesis: claim, supporting_evidence_ids: [evidenceId], contradicting_evidence: [], alternative_explanations: [], confidence: 'low', confidence_rationale: 'Only bounded fixture evidence is available.', recommended_next_checks: [{ instruction: 'Inspect upstream timeouts.', rationale: claim, executed: false }], suggested_remediation: [{ instruction: 'Review connection capacity.', rationale: claim, executed: false }], missing_evidence: ['Live detector result'], limitations: ['Development fixture investigation'], completion_status: 'partial', generated_at: incident.updated_at }, failure: null, additional_evidence: [], fixture_source: true }
  const fetcher = baseFetch(succeeded)
  fetcher.mockImplementationOnce((input) => String(input).endsWith(`/incidents/${incidentId}`) ? response(envelope({ incident: { ...incident, latest_investigation_id: investigationId }, evidence_bundle: null, timeline: { items: [], next_cursor: null, has_more: false }, latest_investigation: null })) : baseFetch(succeeded)(input))
  vi.stubGlobal('fetch', fetcher)
  render(<App />)
  expect((await screen.findAllByText('Errors rose in the triggering minute.')).length).toBeGreaterThan(0)
  fireEvent.click(screen.getAllByRole('button', { name: `Show evidence ${evidenceId}` })[0])
  await waitFor(() => expect(document.getElementById(`evidence-${evidenceId}`)).toHaveAttribute('data-selected', 'true'))
  expect(screen.queryByRole('button', { name: /restart|rollback|fix automatically|apply patch/i })).not.toBeInTheDocument()
})

test('failed investigation displays a safe terminal failure', async () => {
  window.history.replaceState({}, '', `/incidents/${incidentId}`)
  const failed = { investigation_id: investigationId, incident_id: incidentId, evidence_version: 1, state: 'failed', attempt_count: 3, created_at: incident.detected_at, started_at: incident.detected_at, finished_at: incident.updated_at, report: null, failure: { code: 'unavailable', message: 'Reasoning provider is unavailable', retryable: false }, additional_evidence: [], fixture_source: true }
  const fetcher = baseFetch(failed)
  const original = fetcher.getMockImplementation()!
  fetcher.mockImplementation((input, init) => String(input).endsWith(`/incidents/${incidentId}`) ? response(envelope({ incident: { ...incident, latest_investigation_id: investigationId }, evidence_bundle: null, timeline: { items: [], next_cursor: null, has_more: false }, latest_investigation: null })) : original(input, init))
  vi.stubGlobal('fetch', fetcher)
  render(<App />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Reasoning provider is unavailable')
})
