import { useEffect, useState } from 'react'
import { api, type DependenciesResponse, type IncidentSummary, type MetricsResponse, type ServiceDetail } from '../api'
import { Failure, IncidentTable, Loading, PageHeader, StatusBadge } from '../components/Common'
import { MetricChart } from '../components/MetricChart'
import { formatAge, formatTime } from '../format'

type ServiceView = {
  detail: ServiceDetail
  metrics: MetricsResponse
  dependencies: DependenciesResponse
  incidents: IncidentSummary[]
}

export function ServiceDetailPage({ serviceId }: { serviceId: string }) {
  const [data, setData] = useState<ServiceView | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let active = true
    void Promise.all([
      api.service(serviceId),
      api.metrics(serviceId),
      api.dependencies(serviceId),
      api.incidents(`?service_id=${encodeURIComponent(serviceId)}&limit=10`),
    ]).then(([detail, metrics, dependencies, incidents]) => {
      if (active) setData({
        detail: detail.result,
        metrics: metrics.result,
        dependencies: dependencies.result,
        incidents: incidents.result.items,
      })
    }).catch((reason) => {
      if (active) setError(reason instanceof Error ? reason.message : 'Service unavailable')
    })
    return () => { active = false }
  }, [serviceId])
  if (error) return <><PageHeader eyebrow="Service detail" title="Service unavailable" description="The normalized service view could not be loaded." /><Failure message={error} /></>
  if (!data) return <Loading />
  const { summary, latest_bucket: bucket } = data.detail
  const points = data.metrics.buckets.items.map((item) => ({
    time: item.window.start,
    quality: item.quality_status,
    latency: item.latency_p95_ms,
    errors: item.error_rate,
  }))
  return <>
    <PageHeader eyebrow={`${summary.service.namespace} / ${summary.service.environment}`} title={summary.service.name} description={summary.health.reason} action={<StatusBadge value={summary.health.state} />} />
    <section className="kpi-grid compact">
      <article className="kpi"><span>Latency p95</span><strong>{bucket?.latency_p95_ms?.toFixed(1) ?? '—'} ms</strong></article>
      <article className="kpi"><span>Error rate</span><strong>{bucket?.error_rate == null ? '—' : `${(bucket.error_rate * 100).toFixed(1)}%`}</strong></article>
      <article className="kpi"><span>Freshness</span><strong>{formatAge(summary.health.telemetry_age_seconds)}</strong></article>
      <article className="kpi"><span>Active incidents</span><strong>{summary.active_incident_count}</strong></article>
    </section>
    <div className="chart-grid">
      <MetricChart title="Latency p95" unit="ms" points={points.map((point) => ({ time: point.time, value: point.latency, quality: point.quality }))} />
      <MetricChart title="Error rate" unit="%" format={(value) => (value * 100).toFixed(1)} points={points.map((point) => ({ time: point.time, value: point.errors, quality: point.quality }))} />
    </div>
    <section className="content-section">
      <div className="section-title"><div><p className="eyebrow">Observed topology</p><h2>Dependencies</h2></div></div>
      {data.dependencies.edges.items.length ? <div className="dependency-list">{data.dependencies.edges.items.map((edge) => <div key={edge.edge_id}><span>{edge.source_service.name}</span><b>→</b><span>{edge.target_service.name}</span><small>{edge.observed_trace_count ?? 'Unknown'} traces · {formatTime(edge.observed_at)}</small></div>)}</div> : <div className="state-panel">No dependency edges observed in this window.</div>}
    </section>
    <section className="content-section">
      <div className="section-title"><div><p className="eyebrow">Service history</p><h2>Recent incidents</h2></div><a href={`/incidents?service_id=${encodeURIComponent(serviceId)}`}>View queue</a></div>
      <IncidentTable incidents={data.incidents} />
    </section>
  </>
}
