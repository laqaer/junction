import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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

const terminal = vi.hoisted(() => ({ enabled: true, available: true, sent: [] as string[] }))
vi.mock('../../utils/terminalRegistry', () => ({
  useTerminalEnabled: () => terminal.enabled,
  onTerminalReady: (_id: string, cb: () => void) => { cb(); return () => {} },
  sendToTerminalSession: (_id: string, code: string) => { terminal.sent.push(code); return true },
}))
vi.mock('../../hooks/useBottomTerminal', () => ({ addTab: () => terminal.available ? 'term-1' : undefined }))
const clipboard = vi.hoisted(() => ({ copied: [] as string[], succeeds: true }))
vi.mock('../../utils/clipboard', () => ({
  copyToClipboard: async (text: string) => { clipboard.copied.push(text); return clipboard.succeeds },
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

function mount(compact = false) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AgentsPanel compact={compact} />
    </QueryClientProvider>,
  )
}

const harnesses = vi.mocked(api.routingHarnesses)
const checkHarness = vi.mocked(api.checkRoutingHarness)
const editLane = vi.mocked(api.editRoutingLane)
const clearCooldown = vi.mocked(api.clearRoutingCooldown)

beforeEach(() => {
  vi.clearAllMocks()
  terminal.enabled = true
  terminal.available = true
  terminal.sent = []
  clipboard.copied = []
  clipboard.succeeds = true
  checkHarness.mockResolvedValue({ code: 'ok', harness: 'codex', probe: row({}).probe })
  editLane.mockResolvedValue({ code: 'ok', lane: row({}).lane! })
  clearCooldown.mockResolvedValue({ code: 'ok', cleared: [] })
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

  it('falls back to a copy when the enabled terminal cannot open a session', async () => {
    terminal.available = false
    harnesses.mockResolvedValue(view([row({})]))
    mount()

    fireEvent.click(await screen.findByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('button', { name: 'Copied, paste it in a terminal' })).toBeInTheDocument()
    expect(clipboard.copied).toEqual(['codex login'])
    expect(terminal.sent).toEqual([])
  })

  it('reports failure when the setup command can neither run nor be copied', async () => {
    terminal.enabled = false
    clipboard.succeeds = false
    harnesses.mockResolvedValue(view([row({ installed: false, lane: null })]))
    mount()

    fireEvent.click(await screen.findByRole('button', { name: 'Install' }))

    expect(await screen.findByRole('button', { name: 'Could not open a terminal or copy' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Copied, paste it in a terminal' })).toBeNull()
    expect(clipboard.copied).toEqual(['npm i -g @openai/codex'])
    expect(terminal.sent).toEqual([])
  })

  it('copies the displayed command without starting a terminal', async () => {
    harnesses.mockResolvedValue(view([row({})]))
    mount()

    fireEvent.click(await screen.findByRole('button', { name: 'Copy command' }))

    await waitFor(() => expect(clipboard.copied).toEqual(['codex login']))
    expect(terminal.sent).toEqual([])
    expect(screen.getByText('codex login')).toBeInTheDocument()
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

  it.each([
    { label: 'Plan size', draft: '2.5', fields: { weight: 2.5 }, commit: 'blur' },
    { label: 'Tasks per window (5 h)', draft: '2.6', fields: { window_limit: 3 }, commit: 'Enter' },
  ])('saves $label only when the operator commits the draft', async ({ label, draft, fields, commit }) => {
    harnesses.mockResolvedValue(view([row({})]))
    mount()

    const input = await screen.findByRole('spinbutton', { name: label })
    fireEvent.change(input, { target: { value: draft } })
    expect(editLane).not.toHaveBeenCalled()
    if (commit === 'blur') fireEvent.blur(input)
    else fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => expect(editLane).toHaveBeenCalledWith('codex', fields))
    await waitFor(() => expect(harnesses).toHaveBeenCalledTimes(2))
  })

  it.each([
    { label: 'Plan size', invalid: '0', saved: 1 },
    { label: 'Tasks per window (5 h)', invalid: '-1', saved: 0 },
  ])('restores $label after an invalid draft and ignores an unchanged value', async ({ label, invalid, saved }) => {
    harnesses.mockResolvedValue(view([row({})]))
    mount()

    const input = await screen.findByRole('spinbutton', { name: label })
    fireEvent.change(input, { target: { value: invalid } })
    fireEvent.blur(input)
    expect(input).toHaveValue(saved)
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(editLane).not.toHaveBeenCalled()
  })

  it.each([
    { draft: '  chosen-model  ', saved: 'chosen-model', commit: 'Enter' },
    { draft: '   ', saved: '', commit: 'blur' },
  ])('commits a trimmed model as "$saved", including restoring the agent default', async ({ draft, saved, commit }) => {
    const original = row({})
    original.lane!.model = 'previous-model'
    harnesses.mockResolvedValue(view([original]))
    mount()

    const input = await screen.findByRole('textbox', { name: 'Model' })
    fireEvent.change(input, { target: { value: draft } })
    expect(editLane).not.toHaveBeenCalled()
    if (commit === 'blur') fireEvent.blur(input)
    else fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => expect(editLane).toHaveBeenCalledWith('codex', { model: saved }))
  })

  it('checks all installed agents independently and reports a failed check without leaving it busy', async () => {
    harnesses.mockResolvedValue(view([
      row({}),
      row({ harness: 'grok', label: 'Grok Build', lane: null }),
      row({ harness: 'cursor', label: 'Cursor Agent', installed: false, lane: null }),
    ]))
    let finishCodex!: (result: Awaited<ReturnType<typeof api.checkRoutingHarness>>) => void
    let failGrok!: (error: Error) => void
    checkHarness.mockImplementation(harness => harness === 'codex'
      ? new Promise(resolve => { finishCodex = resolve })
      : new Promise((_resolve, reject) => { failGrok = reject }))
    mount()

    fireEvent.click(await screen.findByRole('button', { name: 'Check all' }))
    const codex = screen.getByTestId('agent-codex')
    const grok = screen.getByTestId('agent-grok')
    expect(checkHarness.mock.calls).toEqual([['codex'], ['grok']])
    expect(within(codex).getByText('Checking…')).toBeInTheDocument()
    expect(within(grok).getByRole('button', { name: 'Check', exact: true })).toBeDisabled()
    expect(within(screen.getByTestId('agent-cursor')).queryByRole('button', { name: 'Check', exact: true })).toBeNull()

    await act(async () => { finishCodex({ code: 'ok', harness: 'codex', probe: row({}).probe }) })
    expect(within(codex).getByRole('button', { name: 'Check', exact: true })).toBeEnabled()
    expect(within(grok).getByText('Checking…')).toBeInTheDocument()

    await act(async () => { failGrok(new Error('probe unavailable')) })
    expect(await screen.findByText('The check could not run. Try again in a moment.')).toBeInTheDocument()
    expect(within(grok).getByRole('button', { name: 'Check', exact: true })).toBeEnabled()
    await waitFor(() => expect(harnesses).toHaveBeenCalledTimes(3))
  })

  it('keeps the saved routing state after a failed edit and clears the error after a successful retry', async () => {
    harnesses.mockResolvedValue(view([row({})]))
    editLane.mockRejectedValueOnce(new Error('save unavailable'))
    mount()

    const toggle = await screen.findByRole('switch', { name: 'Use for routing' })
    fireEvent.click(toggle)
    expect(await screen.findByText('Could not save that routing change.')).toBeInTheDocument()
    expect(toggle).toBeChecked()
    await waitFor(() => expect(toggle).toBeEnabled())

    fireEvent.click(toggle)
    await waitFor(() => expect(editLane).toHaveBeenCalledTimes(2))
    expect(editLane).toHaveBeenLastCalledWith('codex', { enabled: false })
    await waitFor(() => expect(screen.queryByText('Could not save that routing change.')).toBeNull())
  })

  it('resumes the cooling lane by its lane id and reloads the routing view', async () => {
    const cooling = row({ cooldown_until: 1_800_000_100, cooldown_reason: 'usage_limit' })
    cooling.lane!.id = 'codex-paid-plan'
    harnesses.mockResolvedValue(view([cooling]))
    mount()

    expect(await screen.findByText(/Resting until/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Resume now' }))

    await waitFor(() => expect(clearCooldown).toHaveBeenCalledWith('codex-paid-plan'))
    await waitFor(() => expect(harnesses).toHaveBeenCalledTimes(2))
  })

  it('reports an unavailable inventory without presenting connection or routing actions', async () => {
    harnesses.mockRejectedValue(new Error('gateway unavailable'))
    mount()

    expect(await screen.findByText('Could not load your agents. Is the gateway running?')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Check all' })).toBeNull()
    expect(screen.queryByRole('switch', { name: 'Use for routing' })).toBeNull()
    expect(screen.queryByText('Who gets what')).toBeNull()
  })

  it('keeps first-run setup focused on connection actions', async () => {
    harnesses.mockResolvedValue(view([row({})]))
    mount(true)

    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Check', exact: true })).toBeInTheDocument()
    expect(screen.queryByRole('switch', { name: 'Use for routing' })).toBeNull()
    expect(screen.queryByRole('textbox', { name: 'Model' })).toBeNull()
    expect(screen.queryByText('Who gets what')).toBeNull()
  })
})
