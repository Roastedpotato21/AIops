import { useCallback, useEffect, useState } from 'react'
import { loadPlatformStatus, type PlatformStatus } from './api'
import './styles.css'

const emptyStatus: PlatformStatus = { health: null, readiness: null, error: null }

export function App() {
  const [status, setStatus] = useState(emptyStatus)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    setLoading(true)
    setStatus(await loadPlatformStatus())
    setLoading(false)
  }, [])

  useEffect(() => {
    let active = true
    void loadPlatformStatus().then((result) => {
      if (active) {
        setStatus(result)
        setLoading(false)
      }
    })
    return () => {
      active = false
    }
  }, [])

  const ready = status.readiness?.status === 'ready'

  return (
    <main>
      <section className="hero">
        <p className="eyebrow">AIOPS · PHASE 1</p>
        <h1>Foundation status</h1>
        <p className="lede">Infrastructure compatibility and API readiness, without simulated incidents.</p>
      </section>

      {status.error ? <div className="alert" role="alert">{status.error}</div> : null}

      <section className="status-grid" aria-label="Platform status">
        <article className="panel">
          <span className="label">API process</span>
          <strong className={status.health ? 'ok' : 'unknown'}>
            {loading ? 'Checking' : status.health?.status === 'ok' ? 'Live' : 'Unavailable'}
          </strong>
          <small>{status.health?.version ?? 'No response'}</small>
        </article>
        <article className="panel">
          <span className="label">Platform readiness</span>
          <strong className={ready ? 'ok' : 'unknown'}>
            {loading ? 'Checking' : ready ? 'Ready' : 'Not ready'}
          </strong>
          <small>{status.readiness?.checked_at ?? 'No response'}</small>
        </article>
      </section>

      <section className="checks" aria-label="Readiness checks">
        <div className="section-heading">
          <h2>Dependency checks</h2>
          <button type="button" onClick={() => void refresh()} disabled={loading}>Refresh</button>
        </div>
        {status.readiness?.checks.map((check) => (
          <div className="check" key={check.name}>
            <span>{check.name.replace('_', ' ')}</span>
            <span className={check.state === 'pass' ? 'badge pass' : 'badge fail'}>
              {check.state === 'pass' ? 'Pass' : check.reason_code?.replace('_', ' ') ?? 'Fail'}
            </span>
          </div>
        )) ?? <p className="empty">Readiness details are unavailable.</p>}
      </section>

      <footer>Phase 1 shell · no detector, incident, or agent features are active.</footer>
    </main>
  )
}
