import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { AgentsPanel } from '../pages/settings/AgentsPanel'
import { api, type RoutingHarnessRow, type RoutingHarnessesView } from '../api/client'

vi.mock('../api/client', () => ({
  api: {
    routingHarnesses: vi.fn(),
    checkRoutingHarness: vi.fn(),
    editRoutingLane: vi.fn(),
    clearRoutingCooldown: vi.fn(),
  },
}))
vi.mock('../utils/terminalRegistry', () => ({
  useTerminalEnabled: () => false,
  onTerminalReady: () => () => {},
  sendToTerminalSession: () => true,
}))
vi.mock('../hooks/useBottomTerminal', () => ({ addTab: () => 'term-1' }))
vi.mock('../utils/clipboard', () => ({ copyToClipboard: async () => true }))

const ALL_KINDS = ['plan', 'implement', 'debug', 'review', 'test', 'research', 'docs', 'quick', 'bulk']

function row(over: Partial<RoutingHarnessRow>): RoutingHarnessRow {
  return {
    harness: 'codex',
    label: 'Codex (ChatGPT)',
    billing: 'subscription',
    featured: true,
    installed: true,
    setup: { install: 'npm i -g @openai/codex', login: 'codex login', docs_url: 'https://example.test/codex' },
    hint: '',
    lane: {
      id: 'codex', harness: 'codex', label: 'Codex (ChatGPT)', billing: 'subscription', enabled: true,
      weight: 1, model: '', window_hours: 5, window_limit: 0, daily_limit: 0,
    },
    lane_count: 1,
    routed: true,
    window_used: 2,
    day_used: 3,
    cooldown_until: 0,
    cooldown_reason: '',
    probe: { status: 'connected', detail: '', models: 4, checked_at: 1_800_000_000 },
    ...over,
  }
}

function view(rows: RoutingHarnessRow[], kinds = ['plan']): RoutingHarnessesView {
  return {
    code: 'ok', enabled: true, source: 'auto', path: '/home/x/.junction/routing.json', warnings: [],
    kinds, preview: Object.fromEntries(kinds.map(k => [k, k === 'unlisted' ? '' : 'codex'])), harnesses: rows,
  }
}

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AgentsPanel />
    </QueryClientProvider>,
  )
}

const harnesses = vi.mocked(api.routingHarnesses)
const checkHarness = vi.mocked(api.checkRoutingHarness)
const editLane = vi.mocked(api.editRoutingLane)
const clearCooldown = vi.mocked(api.clearRoutingCooldown)

beforeEach(() => {
  vi.clearAllMocks()
  checkHarness.mockResolvedValue({ code: 'ok', harness: 'codex', probe: row({}).probe })
  editLane.mockResolvedValue({ code: 'ok', lane: row({}).lane! })
  clearCooldown.mockResolvedValue({ code: 'ok' } as Awaited<ReturnType<typeof api.clearRoutingCooldown>>)
})

describe('AgentsPanel, routing details', () => {
  it('names every task kind in the pick grid, and shows an unknown kind as itself', async () => {
    harnesses.mockResolvedValue(view([row({})], [...ALL_KINDS, 'unlisted']))
    mount()

    for (const label of ['Planning', 'Coding', 'Debugging', 'Code review', 'Tests', 'Research', 'Writing docs', 'Quick edits', 'Bulk changes']) {
      expect(await screen.findByText(label)).toBeInTheDocument()
    }
    expect(screen.getByText('unlisted')).toBeInTheDocument()
  })

  it('shows a probe that timed out or failed', async () => {
    harnesses.mockResolvedValue(view([
      row({ probe: { status: 'timeout', detail: '', models: 0, checked_at: 1 } }),
      row({ harness: 'grok', label: 'Grok Build', lane: null, probe: { status: 'error', detail: 'boom', models: 0, checked_at: 1 } }),
    ]))
    mount()

    expect(within(await screen.findByTestId('agent-codex')).getByText('No response')).toBeInTheDocument()
    expect(within(screen.getByTestId('agent-grok')).getByText('Error')).toBeInTheDocument()
    expect(screen.getByText('boom')).toBeInTheDocument()
  })

  it('says so when a check cannot run, and checks every installed agent on Check all', async () => {
    harnesses.mockResolvedValue(view([
      row({}),
      row({ harness: 'grok', label: 'Grok Build', lane: null }),
      row({ harness: 'cursor', label: 'Cursor Agent', installed: false, lane: null }),
    ]))
    checkHarness.mockRejectedValueOnce(new Error('down'))
    mount()

    fireEvent.click(within(await screen.findByTestId('agent-codex')).getByRole('button', { name: /^Check$/ }))
    expect(await screen.findByText('The check could not run. Try again in a moment.')).toBeInTheDocument()

    checkHarness.mockClear()
    fireEvent.click(screen.getByRole('button', { name: /Check all/ }))
    await waitFor(() => expect(checkHarness).toHaveBeenCalledTimes(2))
    expect(checkHarness.mock.calls.map(c => c[0]).sort()).toEqual(['codex', 'grok'])
  })

  it('says so when a routing change cannot be saved', async () => {
    harnesses.mockResolvedValue(view([row({})]))
    editLane.mockRejectedValueOnce(new Error('denied'))
    mount()

    fireEvent.click(await screen.findByRole('switch', { name: /Use for routing/ }))
    expect(await screen.findByText('Could not save that routing change.')).toBeInTheDocument()
  })

  it('saves plan size, task limit and model on blur or Enter, and ignores an invalid number', async () => {
    harnesses.mockResolvedValue(view([row({})]))
    mount()

    const size = await screen.findByLabelText('Plan size')
    fireEvent.change(size, { target: { value: '-3' } })
    fireEvent.blur(size)
    expect(editLane).not.toHaveBeenCalled()
    expect(size).toHaveValue(1)

    fireEvent.change(size, { target: { value: '2' } })
    fireEvent.blur(size)
    await waitFor(() => expect(editLane).toHaveBeenCalledWith('codex', { weight: 2 }))

    const limit = screen.getByLabelText('Tasks per window (5 h)')
    fireEvent.change(limit, { target: { value: '3.4' } })
    fireEvent.keyDown(limit, { key: 'Enter' })
    await waitFor(() => expect(editLane).toHaveBeenCalledWith('codex', { window_limit: 3 }))

    const model = screen.getByLabelText('Model')
    fireEvent.change(model, { target: { value: '  gpt-5  ' } })
    fireEvent.keyDown(model, { key: 'Enter' })
    await waitFor(() => expect(editLane).toHaveBeenCalledWith('codex', { model: 'gpt-5' }))
  })

  it('resumes a resting agent', async () => {
    harnesses.mockResolvedValue(view([row({ cooldown_until: 1_900_000_000, cooldown_reason: 'rate_limit' })]))
    mount()

    fireEvent.click(await screen.findByRole('button', { name: /Resume now/ }))
    await waitFor(() => expect(clearCooldown).toHaveBeenCalledWith('codex'))
  })
})
