import { lazy, Suspense, useEffect, useState } from 'react'
import { IncidentDetailPage } from './pages/IncidentDetailPage'
import { IncidentsPage } from './pages/IncidentsPage'
import { OverviewPage } from './pages/OverviewPage'
import { ServicesPage } from './pages/ServicesPage'
import { Loading } from './components/Common'
import './styles.css'

const ServiceDetailPage = lazy(async () => {
  const module = await import('./pages/ServiceDetailPage')
  return { default: module.ServiceDetailPage }
})

function route(pathname: string) {
  const incident = pathname.match(/^\/incidents\/(incident_[0-9a-f]{64})$/)
  if (incident) return <IncidentDetailPage incidentId={incident[1]} />
  const service = pathname.match(/^\/services\/(svc_[0-9a-f]{64})$/)
  if (service) return <Suspense fallback={<Loading label="Loading service telemetry…" />}><ServiceDetailPage serviceId={service[1]} /></Suspense>
  if (pathname === '/incidents') return <IncidentsPage />
  if (pathname === '/services') return <ServicesPage />
  return <OverviewPage />
}

export function App() {
  const [pathname, setPathname] = useState(window.location.pathname)
  useEffect(() => {
    const update = () => setPathname(window.location.pathname)
    window.addEventListener('popstate', update)
    return () => window.removeEventListener('popstate', update)
  }, [])
  const navigate = (event: React.MouseEvent<HTMLAnchorElement>) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey) return
    event.preventDefault()
    window.history.pushState({}, '', event.currentTarget.href)
    setPathname(window.location.pathname)
  }
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="/" onClick={navigate}><span className="brand-mark">A</span><span>AIOps <span className="muted">/ beta</span></span></a>
        <nav aria-label="Main navigation">
          <a className={pathname === '/' ? 'active' : ''} href="/" onClick={navigate}>Overview</a>
          <a className={pathname.startsWith('/services') ? 'active' : ''} href="/services" onClick={navigate}>Services</a>
          <a className={pathname.startsWith('/incidents') ? 'active' : ''} href="/incidents" onClick={navigate}>Incidents</a>
        </nav>
        <p className="sidebar-foot"><span className="pulse" /> Local operations plane</p>
      </aside>
      <main>{route(pathname)}</main>
    </div>
  )
}
