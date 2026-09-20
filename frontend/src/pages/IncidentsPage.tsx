import { useEffect, useState } from 'react'
import { api, type IncidentSummary } from '../api'
import { Failure, IncidentTable, Loading, PageHeader } from '../components/Common'

export function IncidentsPage() {
  const [items, setItems] = useState<IncidentSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [state, setState] = useState('')
  const [severity, setSeverity] = useState('')
  const [service, setService] = useState('')
  useEffect(() => { let active = true; const params = new URLSearchParams(); if (state) params.set('state', state); if (severity) params.set('severity', severity); if (service) params.set('service_id', service); const query = params.size ? `?${params}` : ''; void api.incidents(query).then((response) => { if (active) { setItems(response.result.items); setError(null) } }).catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : 'Incidents unavailable') }); return () => { active = false } }, [state, severity, service])
  const services = Array.from(new Map((items ?? []).map((item) => [item.primary_service.service_id, item.primary_service])).values())
  return <><PageHeader eyebrow="Incident operations" title="Incidents" description="Deterministic episodes with bounded evidence and investigation state." /><fieldset className="filters"><legend>Filter incidents</legend><label>State<select value={state} onChange={(event) => setState(event.target.value)}><option value="">All states</option><option value="open">Open</option><option value="recovering">Recovering</option><option value="resolved">Resolved</option></select></label><label>Severity<select value={severity} onChange={(event) => setSeverity(event.target.value)}><option value="">All severities</option>{['critical', 'high', 'medium', 'low'].map((value) => <option key={value}>{value}</option>)}</select></label><label>Service<select value={service} onChange={(event) => setService(event.target.value)}><option value="">All services</option>{services.map((item) => <option value={item.service_id} key={item.service_id}>{item.name}</option>)}</select></label></fieldset>{error ? <Failure message={error} /> : !items ? <Loading /> : <IncidentTable incidents={items} />}</>
}
