import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { AgentsPanel } from './AgentsPanel'
import { api, type RoutingHarnessRow, type RoutingHarnessesView } from '../../api/client'

vi.mock('../../api/client', () => ({
  api: {
    routingHarnesses: vi.fn(),
    checkRoutingHarness: vi.fn(),
    editRoutingLane: vi.fn(),
    clearRoutingCooldown: vi.fn(),
  },
}))

const terminal = vi.hoisted(() => ({ enabled: true, sent: [] as string[] }))
vi.mock('../../utils/terminalRegistry', () => ({
  useTerminalEnabled: () => terminal.enabled,
  onTerminalReady: (_id: string, cb: () => void) => { cb(); return () => {} },
  sendToTerminalSession: (_id: string, code: string) => { terminal.sent.push(code); return true },
}))
vi.mock('../../hooks/useBottomTerminal', () => ({ addTab: () => 'term-1' }))
const clipboard = vi.hoisted(() => ({ copied: [] as string[] }))
vi.mock('../../utils/clipboard', () => ({
  copyToClipboard: async (text: string) => { clipboard.copied.push(text); return true },
}))

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

function view(rows: RoutingHarnessRow[]): RoutingHarnessesView {
  return {
    code: 'ok', enabled: true, source: 'auto', path: '/home/x/.junction/routing.json', warnings: [],
    kinds: ['plan', 'implement'], preview: { plan: 'codex', implement: '' }, harnesses: rows,
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

beforeEach(() => {
  vi.clearAllMocks()
  terminal.enabled = true
  terminal.sent = []
  clipboard.copied = []
  checkHarness.mockResolvedValue({ code: 'ok', harness: 'codex', probe: row({}).probe })
  editLane.mockResolvedValue({ code: 'ok', lane: row({}).lane! })
})

describe('AgentsPanel', () => {
  it('shows each agent with its connection status and the routing picks', async () => {
    harnesses.mockResolvedValue(view([
      row({}),
      row({
        harness: 'grok', label: 'Grok Build', lane: null, routed: false,
        probe: { status: 'needs_login', detail: 'Authentication required', models: 0, checked_at: 1_800_000_000 },
        setup: { install: 'npm i -g @xai-official/grok', login: 'grok login', docs_url: 'https://example.test/grok' },
      }),
      row({ harness: 'cursor', label: 'Cursor Agent', installed: false, lane: null, routed: false }),
    ]))
    mount()

    const codex = await screen.findByTestId('agent-codex')
    expect(within(codex).getByText('Connected')).toBeInTheDocument()
    expect(within(await screen.findByTestId('agent-grok')).getByText('Needs sign-in')).toBeInTheDocument()
    expect(screen.getByText('Authentication required')).toBeInTheDocument()
    expect(within(screen.getByTestId('agent-cursor')).getByText('Not installed')).toBeInTheDocument()
    // The pick grid names the lane's agent, and says so when a kind has none.
    expect(screen.getByText('Planning')).toBeInTheDocument()
    expect(screen.getByText('No agent available')).toBeInTheDocument()
  })

  it('runs the sign-in command in the dock terminal', async () => {
    harnesses.mockResolvedValue(view([
      row({ probe: { status: 'needs_login', detail: '', models: 0, checked_at: 1 } }),
    ]))
    mount()

    fireEvent.click(await screen.findByRole('button', { name: /Sign in/ }))
    await waitFor(() => expect(terminal.sent).toEqual(['codex login']))
    expect(await screen.findByText('Opened in terminal')).toBeInTheDocument()
  })

  it('copies the command instead when the terminal is off', async () => {
    terminal.enabled = false
    harnesses.mockResolvedValue(view([row({ installed: false, lane: null })]))
    mount()

    fireEvent.click(await screen.findByRole('button', { name: /Install/ }))
    await waitFor(() => expect(clipboard.copied).toEqual(['npm i -g @openai/codex']))
    expect(terminal.sent).toEqual([])
  })

  it('probes installed agents that were never checked, once', async () => {
    harnesses.mockResolvedValue(view([
      row({ probe: { status: 'unknown', detail: '', models: 0, checked_at: 0 } }),
      row({ harness: 'cursor', installed: false, lane: null, probe: { status: 'unknown', detail: '', models: 0, checked_at: 0 } }),
    ]))
    mount()

    await waitFor(() => expect(checkHarness).toHaveBeenCalledTimes(1))
    expect(checkHarness).toHaveBeenCalledWith('codex')
  })

  it('writes routing changes for that agent', async () => {
    harnesses.mockResolvedValue(view([row({})]))
    mount()

    fireEvent.click(await screen.findByRole('switch', { name: /Use for routing/ }))
    await waitFor(() => expect(editLane).toHaveBeenCalledWith('codex', { enabled: false }))
  })

  it('offers the install command when an installed agent is missing a piece', async () => {
    // Claude Code without its ACP adapter: the CLI is on PATH, but the probe
    // says not installed, so Sign in would be the wrong next step.
    harnesses.mockResolvedValue(view([row({
      harness: 'claude', label: 'Claude Code',
      setup: { install: 'npm i -g claude-pieces', login: 'claude auth login', docs_url: 'https://example.test/c' },
      probe: { status: 'not_installed', detail: 'claude-agent-acp not found', models: 0, checked_at: 1 },
    })]))
    mount()

    const card = await screen.findByTestId('agent-claude')
    expect(within(card).getByText('Not installed')).toBeInTheDocument()
    expect(within(card).queryByRole('button', { name: /Sign in/ })).toBeNull()
    fireEvent.click(within(card).getByRole('button', { name: /Install/ }))
    await waitFor(() => expect(terminal.sent).toEqual(['npm i -g claude-pieces']))
  })

  it('fills in the installed and model counts', async () => {
    harnesses.mockResolvedValue(view([row({})]))
    mount()

    expect(await screen.findByText('Installed: 1')).toBeInTheDocument()
    expect(screen.getByText(/Models: 4/)).toBeInTheDocument()
  })
})
