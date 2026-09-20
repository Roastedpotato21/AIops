import { useEffect, useMemo, useState } from 'react'
import { api, type EvidenceItem, type IncidentDetail } from '../api'
import { EvidenceList } from '../components/EvidenceList'
import { FixtureBadge, Failure, Loading, PageHeader, StatusBadge } from '../components/Common'
import { formatTime } from '../format'
import { InvestigationPanel } from '../components/InvestigationPanel'

export function IncidentDetailPage({ incidentId }: { incidentId: string }) {
  const [detail, setDetail] = useState<IncidentDetail | null>(null)
  const [evidence, setEvidence] = useState<EvidenceItem[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { let active = true; void Promise.all([api.incident(incidentId), api.evidence(incidentId)]).then(([incident, items]) => { if (active) { setDetail(incident.result); setEvidence(items.result.items.items) } }).catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : 'Incident unavailable') }); return () => { active = false } }, [incidentId])
  const byType = useMemo(() => evidence.reduce<Record<string, EvidenceItem[]>>((groups, item) => {
    const items = groups[item.evidence_type] ?? []
    items.push(item)
    groups[item.evidence_type] = items
    return groups
  }, {}), [evidence])
  const showEvidence = (id: string) => {
    setSelected(id)
    window.setTimeout(() => {
      const target = document.getElementById(`evidence-${id}`)
      if (target && typeof target.scrollIntoView === 'function') target.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 0)
  }
  if (error) return <><PageHeader eyebrow="Incident detail" title="Incident unavailable" description="The persisted incident or evidence bundle could not be loaded." /><Failure message={error} /></>
  if (!detail) return <Loading />
  const incident = detail.incident
  const trigger = evidence.find((item) => item.evidence_type === 'metric_bucket')
  const snapshot = trigger?.snapshot as { latency_p95_ms?: number; error_rate?: number; window?: { start: string; end: string } } | undefined
  return <><PageHeader eyebrow={`Incident · ${incident.incident_id.slice(0, 18)}…`} title={`${incident.primary_service.name} ${incident.feature === 'latency_p95_ms' ? 'latency' : 'errors'}`} description={incident.severity_reason} action={<div className="header-badges"><StatusBadge value={incident.severity} /><StatusBadge value={incident.state} /></div>} /><FixtureBadge visible={incident.fixture_source} /><section className="incident-meta"><div><span>Opened</span><strong>{formatTime(incident.detected_at)}</strong></div><div><span>Affected window</span><strong>{formatTime(incident.first_affected_at)} → {formatTime(incident.last_affected_at)}</strong></div><div><span>Evidence</span><strong>{incident.evidence_status} · revision {incident.evidence_version}</strong></div></section><section className="content-section"><div className="section-title"><div><p className="eyebrow">Triggering metric</p><h2>Observed impact</h2></div><StatusBadge value={trigger?.quality_status ?? 'unknown'} /></div><div className="metric-evidence"><div><span>Current</span><strong>{incident.feature === 'latency_p95_ms' ? `${snapshot?.latency_p95_ms?.toFixed(1) ?? '—'} ms` : snapshot?.error_rate == null ? '—' : `${(snapshot.error_rate * 100).toFixed(1)}%`}</strong></div><div><span>Frozen baseline</span><strong>{incident.feature === 'latency_p95_ms' ? `${incident.recovery_baseline?.latency_p95_median_ms?.toFixed(1) ?? 'Unavailable'} ms` : incident.recovery_baseline ? `${(incident.recovery_baseline.error_rate_median * 100).toFixed(1)}%` : 'Unavailable'}</strong></div><div><span>Window</span><strong>{trigger ? `${formatTime(trigger.window.start)} – ${formatTime(trigger.window.end)}` : 'Unavailable'}</strong></div></div></section><section className="content-section"><div className="section-title"><div><p className="eyebrow">Chronology</p><h2>Timeline</h2></div></div><ol className="timeline">{detail.timeline.items.map((item) => <li key={item.entry_id}><time>{formatTime(item.occurred_at)}</time><div><strong>{item.kind.replaceAll('_', ' ')}</strong><p>{item.summary}</p>{item.evidence_ids.map((id) => <button type="button" className="citation-button" onClick={() => showEvidence(id)} key={id}>{id.slice(0, 12)}</button>)}</div></li>)}</ol></section><section className="content-section"><div className="section-title"><div><p className="eyebrow">Bounded evidence</p><h2>Evidence bundle</h2></div><span>{evidence.length} items</span></div><div className="evidence-counts">{Object.entries(byType).map(([type, items]) => <span key={type}>{type.replaceAll('_', ' ')} <b>{items?.length ?? 0}</b></span>)}</div><EvidenceList items={evidence} selectedId={selected} onSelect={setSelected} /></section><InvestigationPanel incidentId={incidentId} initialId={incident.latest_investigation_id} fixtureSource={incident.fixture_source} onEvidence={showEvidence} /></>
}
