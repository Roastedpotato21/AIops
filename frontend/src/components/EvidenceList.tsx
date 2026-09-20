import { useState } from 'react'
import type { EvidenceItem } from '../api'
import { formatTime } from '../format'
import { Empty, StatusBadge } from './Common'

export function EvidenceList({ items, selectedId, onSelect }: { items: EvidenceItem[]; selectedId?: string | null; onSelect?: (id: string | null) => void }) {
  const [localExpanded, setLocalExpanded] = useState<string | null>(null)
  const expanded = selectedId === undefined ? localExpanded : selectedId
  if (!items.length) return <Empty message="No evidence items are available in this bundle." />
  const select = (id: string) => {
    const next = expanded === id ? null : id
    setLocalExpanded(next)
    onSelect?.(next)
  }
  return <div className="evidence-list">{items.map((item) => {
    const isExpanded = expanded === item.evidence_id
    return <article className={`evidence-card ${isExpanded ? 'selected' : ''}`} data-selected={isExpanded} id={`evidence-${item.evidence_id}`} key={item.evidence_id}><button type="button" className="evidence-summary" aria-expanded={isExpanded} onClick={() => select(item.evidence_id)}><span className="evidence-icon">{item.evidence_type.slice(0, 2).toUpperCase()}</span><span><strong>{item.summary}</strong><small>{item.evidence_type.replaceAll('_', ' ')} · {formatTime(item.window.start)}</small></span><StatusBadge value={item.quality_status} /></button>{isExpanded ? <div className="technical-detail"><div><span>Evidence ID</span><code>{item.evidence_id}</code></div><div><span>Window</span><code>{item.window.start} → {item.window.end}</code></div><div><span>Redaction</span><code>{item.redaction_status}</code></div><details><summary>Technical snapshot</summary><pre>{JSON.stringify(item.snapshot, null, 2)}</pre></details></div> : null}</article>
  })}</div>
}
