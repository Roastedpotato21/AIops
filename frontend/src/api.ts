export type HealthResponse = {
  status: 'ok'
  service: 'aiops-api'
  version: string
  checked_at: string
}

export type ReadinessCheck = {
  name: 'configuration' | 'opensearch' | 'bootstrap'
  state: 'pass' | 'fail'
  reason_code: 'missing_config' | 'unreachable' | 'unauthorized' | 'bootstrap_pending' | null
  checked_at: string
}

export type ReadyResponse = {
  status: 'ready' | 'not_ready'
  checked_at: string
  checks: ReadinessCheck[]
}

export type PlatformStatus = {
  health: HealthResponse | null
  readiness: ReadyResponse | null
  error: string | null
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { headers: { Accept: 'application/json' } })
  const body = (await response.json()) as T
  if (!response.ok && response.status !== 503) {
    throw new Error(`API request failed (${response.status})`)
  }
  return body
}

export async function loadPlatformStatus(): Promise<PlatformStatus> {
  try {
    const [health, readiness] = await Promise.all([
      fetchJson<HealthResponse>('/health'),
      fetchJson<ReadyResponse>('/ready'),
    ])
    return { health, readiness, error: null }
  } catch {
    return { health: null, readiness: null, error: 'The local API is unavailable.' }
  }
}
