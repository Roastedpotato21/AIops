import { render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { App } from './App'

afterEach(() => vi.restoreAllMocks())

test('renders real readiness response', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ status: 'ok', service: 'aiops-api', version: 'test', checked_at: '2026-09-19T12:00:00Z' }) })
    .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ status: 'ready', checked_at: '2026-09-19T12:00:00Z', checks: [{ name: 'configuration', state: 'pass', reason_code: null, checked_at: '2026-09-19T12:00:00Z' }] }) }))
  render(<App />)
  expect(await screen.findByText('Ready')).toBeInTheDocument()
  expect(screen.getByText('configuration')).toBeInTheDocument()
})

test('shows unavailable API without fake status', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
  render(<App />)
  expect(await screen.findByRole('alert')).toHaveTextContent('local API is unavailable')
})
