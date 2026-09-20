import type { HealthState, IncidentSummary, QualityState, Severity } from '../api'
import { formatTime } from '../format'

export function StatusBadge({ value }: { value: HealthState | Severity | QualityState | string }) {
  return <span className={`status status-${value}`}>{value.replaceAll('_', ' ')}</span>
}

export function FixtureBadge({ visible }: { visible: boolean }) {
  return visible ? <span className="fixture-badge">Development fixture — not produced by live RCF</span> : null
}

export function PageHeader({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: React.ReactNode }) {
  return <header className="page-header"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p>{description}</p></div>{action}</header>
}

export function Loading({ label = 'Loading operational data…' }: { label?: string }) { return <div className="state-panel" role="status"><span className="spinner" />{label}</div> }
export function Failure({ message }: { message: string }) { return <div className="state-panel error" role="alert"><strong>Data unavailable</strong><span>{message}</span></div> }
export function Empty({ message }: { message: string }) { return <div className="state-panel"><strong>No data</strong><span>{message}</span></div> }

export function IncidentTable({ incidents }: { incidents: IncidentSummary[] }) {
  if (!incidents.length) return <Empty message="No incidents match this view." />
  return <div className="table-wrap"><table><thead><tr><th>Severity</th><th>Service</th><th>Symptom</th><th>State</th><th>Opened</th><th>Updated</th><th>Investigation</th></tr></thead><tbody>{incidents.map((item) => <tr key={item.incident_id}><td><StatusBadge value={item.severity} /></td><td><a href={`/incidents/${item.incident_id}`}>{item.primary_service.name}</a>{item.fixture_source ? <span className="fixture-mini">fixture</span> : null}</td><td>{item.feature === 'latency_p95_ms' ? 'Latency p95' : 'Error rate'}</td><td><StatusBadge value={item.state} /></td><td>{formatTime(item.detected_at)}</td><td>{formatTime(item.updated_at)}</td><td>{item.latest_investigation_id ? 'Available' : 'Not requested'}</td></tr>)}</tbody></table></div>
}
