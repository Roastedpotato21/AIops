import { useEffect, useState } from 'react'
import { api, type EvidenceClaim, type InvestigationView } from '../api'
import { Failure, FixtureBadge, Loading, StatusBadge } from './Common'

function Citation({ claim, onEvidence }: { claim: EvidenceClaim; onEvidence: (id: string) => void }) {
  return <p className="claim">{claim.statement} <span className="citations">{claim.evidence_ids.map((id) => <button type="button" key={id} onClick={() => onEvidence(id)} aria-label={`Show evidence ${id}`}>[{id.slice(0, 10)}]</button>)}</span></p>
}

export function InvestigationPanel({ incidentId, initialId, fixtureSource, onEvidence }: { incidentId: string; initialId: string | null; fixtureSource: boolean; onEvidence: (id: string) => void }) {
  const [investigation, setInvestigation] = useState<InvestigationView | null>(null)
  const [id, setId] = useState(initialId)
  const [loading, setLoading] = useState(Boolean(initialId))
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    let active = true
    let timer: number | undefined
    const poll = async () => {
      try {
        const response = await api.investigation(id)
        if (!active) return
        setInvestigation(response.result)
        setLoading(false)
        if (response.result.state === 'queued' || response.result.state === 'running') timer = window.setTimeout(() => void poll(), 2000)
      } catch (reason) {
        if (active) { setError(reason instanceof Error ? reason.message : 'Investigation unavailable'); setLoading(false) }
      }
    }
    void poll()
    return () => { active = false; if (timer) window.clearTimeout(timer) }
  }, [id])

  const investigate = async () => {
    setLoading(true); setError(null)
    try {
      const key = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${incidentId}`
      const response = await api.investigate(incidentId, key)
      setId(response.result.investigation_id)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Investigation request failed'); setLoading(false) }
  }

  if (!id) return <section className="panel investigation"><div className="section-title"><div><p className="eyebrow">AI investigation</p><h2>Evidence-guided analysis</h2></div><button type="button" className="primary" onClick={() => void investigate()} disabled={loading}>Investigate with AI</button></div><p className="muted">Starts an asynchronous, bounded, read-only investigation. No remediation is executed.</p>{error ? <Failure message={error} /> : null}</section>
  if (loading && !investigation) return <section className="panel investigation"><Loading label="Loading investigation…" /></section>
  if (error) return <section className="panel investigation"><Failure message={error} /></section>
  if (!investigation) return null
  const report = investigation.report
  return <section className="panel investigation"><div className="section-title"><div><p className="eyebrow">AI investigation</p><h2>Investigation report</h2></div><StatusBadge value={investigation.state} /></div><FixtureBadge visible={investigation.fixture_source || fixtureSource} />{investigation.state === 'queued' || investigation.state === 'running' ? <div className="progress-state"><span className="spinner" /><strong>{investigation.state === 'queued' ? 'Queued for analysis' : 'Analyzing bounded evidence'}</strong><p>This page polls the persisted job; no request is held open.</p></div> : null}{investigation.state === 'failed' ? <Failure message={investigation.failure?.message ?? 'Investigation failed safely.'} /> : null}{report ? <div className="report"><div className="report-lead"><StatusBadge value={report.confidence} /><span>Qualitative confidence · {report.completion_status.replaceAll('_', ' ')}</span></div><h3>Summary</h3><Citation claim={report.summary} onEvidence={onEvidence} /><div className="report-grid"><div><h3>Suspected root service</h3><p>{report.suspected_root_service?.name ?? 'Not established'}</p>{report.root_service_claim ? <Citation claim={report.root_service_claim} onEvidence={onEvidence} /> : null}</div><div><h3>Primary hypothesis</h3>{report.primary_hypothesis ? <Citation claim={report.primary_hypothesis} onEvidence={onEvidence} /> : <p>Insufficient evidence for a primary hypothesis.</p>}</div></div><h3>Confidence rationale</h3><p>{report.confidence_rationale}</p><ReportClaims title="Contradicting evidence" claims={report.contradicting_evidence} onEvidence={onEvidence} /><ReportClaims title="Alternative explanations" claims={report.alternative_explanations} onEvidence={onEvidence} /><ActionList title="Recommended next checks" actions={report.recommended_next_checks} onEvidence={onEvidence} /><ActionList title="Suggested remediation — advice only" actions={report.suggested_remediation} onEvidence={onEvidence} /><TextList title="Missing evidence" items={report.missing_evidence} /><TextList title="Limitations" items={report.limitations} /></div> : null}</section>
}

function ReportClaims({ title, claims, onEvidence }: { title: string; claims: EvidenceClaim[]; onEvidence: (id: string) => void }) { if (!claims.length) return null; return <div><h3>{title}</h3>{claims.map((claim, index) => <Citation key={`${title}-${index}`} claim={claim} onEvidence={onEvidence} />)}</div> }
function ActionList({ title, actions, onEvidence }: { title: string; actions: Array<{ instruction: string; rationale: EvidenceClaim; executed: false }>; onEvidence: (id: string) => void }) { if (!actions.length) return null; return <div><h3>{title}</h3><ul>{actions.map((action) => <li key={action.instruction}><strong>{action.instruction}</strong><Citation claim={action.rationale} onEvidence={onEvidence} /></li>)}</ul></div> }
function TextList({ title, items }: { title: string; items: string[] }) { return items.length ? <div><h3>{title}</h3><ul>{items.map((item) => <li key={item}>{item}</li>)}</ul></div> : null }
