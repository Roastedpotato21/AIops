import { useEffect, useState } from 'react'
import { api, type Overview, type ReadyResponse, type ServiceDetail } from '../api'
import { Failure, IncidentTable, Loading, PageHeader, StatusBadge } from '../components/Common'
import { formatAge } from '../format'

export function OverviewPage() {
  const [data, setData] = useState<Overview | null>(null)
  const [ready, setReady] = useState<ReadyResponse | null>(null)
  const [services, setServices] = useState<ServiceDetail[]>([])
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let active = true
    void Promise.all([api.overview(), api.ready(), api.services()]).then(async ([overview, readiness, servicePage]) => {
      const details = await Promise.all(servicePage.result.items.map((item) => api.service(item.service.service_id)))
      if (active) { setData(overview.result); setReady(readiness); setServices(details.map((item) => item.result)) }
    }).catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : 'Overview unavailable') })
    return () => { active = false }
  }, [])
  const oldestAge = services.reduce<number | null>((oldest, item) => {
    const age = item.summary.health.telemetry_age_seconds
    return age !== null && (oldest === null || age > oldest) ? age : oldest
  }, null)
  return <><PageHeader eyebrow="Operations overview" title="System at a glance" description="Live product state from FastAPI. Unknown and stale signals remain explicit." />{error ? <Failure message={error} /> : !data ? <Loading /> : <><section className="kpi-grid"><article className="kpi hero-kpi"><span>Overall health</span><StatusBadge value={data.overall_health} /><small>{data.service_counts.unknown} services unknown</small></article><article className="kpi"><span>API readiness</span><strong>{ready?.status === 'ready' ? 'Ready' : 'Not ready'}</strong><small>{ready?.checked_at ?? 'No response'}</small></article><article className="kpi"><span>Active incidents</span><strong>{data.active_incident_count}</strong><small>Open and recovering</small></article><article className="kpi"><span>Telemetry freshness</span><strong>{formatAge(oldestAge)}</strong><small>Oldest available raw freshness</small></article></section><section className="content-section"><div className="section-title"><div><p className="eyebrow">Monitored services</p><h2>Service health</h2></div><a href="/services">View all</a></div><div className="service-grid">{services.map(({ summary, latest_bucket: bucket }) => <a className="service-card" href={`/services/${summary.service.service_id}`} key={summary.service.service_id}><div><span className="service-icon">{summary.service.name.slice(0, 2).toUpperCase()}</span><StatusBadge value={summary.health.state} /></div><h3>{summary.service.name}</h3><p>{summary.health.reason}</p><dl><div><dt>Latency p95</dt><dd>{bucket?.latency_p95_ms?.toFixed(1) ?? '—'} ms</dd></div><div><dt>Error rate</dt><dd>{bucket?.error_rate == null ? '—' : `${(bucket.error_rate * 100).toFixed(1)}%`}</dd></div><div><dt>Freshness</dt><dd>{formatAge(summary.health.telemetry_age_seconds)}</dd></div><div><dt>Active incidents</dt><dd>{summary.active_incident_count}</dd></div></dl></a>)}</div></section><section className="content-section"><div className="section-title"><div><p className="eyebrow">Active and recent</p><h2>Incidents</h2></div><a href="/incidents">Open incident queue</a></div><IncidentTable incidents={data.recent_incidents} /></section><section className="content-section"><div className="section-title"><div><p className="eyebrow">Platform components</p><h2>Runtime visibility</h2></div></div><div className="component-list">{data.components.map((item) => <div key={item.name}><span>{item.name.replaceAll('_', ' ')}</span><StatusBadge value={item.state} /><small>{item.reason ?? 'Responding normally'}</small></div>)}</div></section></>}</>
}
