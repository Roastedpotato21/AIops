import { useEffect, useState } from 'react'
import { api, type ServiceDetail } from '../api'
import { Failure, Loading, PageHeader, StatusBadge } from '../components/Common'
import { formatAge } from '../format'

export function ServicesPage() {
  const [items, setItems] = useState<ServiceDetail[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { let active = true; void api.services().then(async (response) => Promise.all(response.result.items.map((item) => api.service(item.service.service_id)))).then((details) => { if (active) setItems(details.map((item) => item.result)) }).catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : 'Services unavailable') }); return () => { active = false } }, [])
  return <><PageHeader eyebrow="Service inventory" title="Monitored services" description="Current feature health, freshness, and incident load for registered services." />{error ? <Failure message={error} /> : !items ? <Loading /> : <div className="table-wrap"><table><thead><tr><th>Service</th><th>Environment</th><th>Health</th><th>p95 latency</th><th>Error rate</th><th>Freshness</th><th>Incidents</th></tr></thead><tbody>{items.map(({ summary, latest_bucket: bucket }) => <tr key={summary.service.service_id}><td><a href={`/services/${summary.service.service_id}`}>{summary.service.name}</a><small>{summary.service.namespace}</small></td><td>{summary.service.environment}</td><td><StatusBadge value={summary.health.state} /><small>{summary.health.reason}</small></td><td>{bucket?.latency_p95_ms?.toFixed(1) ?? '—'} ms</td><td>{bucket?.error_rate == null ? '—' : `${(bucket.error_rate * 100).toFixed(1)}%`}</td><td>{formatAge(summary.health.telemetry_age_seconds)}</td><td>{summary.active_incident_count}</td></tr>)}</tbody></table></div>}</>
}
