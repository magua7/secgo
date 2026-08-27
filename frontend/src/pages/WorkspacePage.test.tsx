import { useState } from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { WorkspacePage } from './WorkspacePage'

function ControlledWorkspace() {
  const [rightVisible, setRightVisible] = useState(true)
  return <WorkspacePage rightVisible={rightVisible} setRightVisible={setRightVisible} />
}

vi.mock('../hooks/useExecutionRegistry', () => ({
  useExecutionRegistry: () => ({
    selectedId: null,
    selectedState: {
      status: 'idle', phase: 'idle', activeAgent: 'planner', tasks: [], timeline: [], tools: [], evidence: [],
      findings: [], completedSteps: [], keyFindings: [], narrativeUpdates: [], keyProgress: [],
      report: '', currentActivity: '', assistantReply: '', finalAnswer: '', lastAssistantOutput: '',
      lastStreamAgent: null, startedAt: null, endedAt: null, totalSteps: 0, reason: '',
      error: null, executionExpanded: true, connection: 'idle',
    },
    runtimes: {},
    startSession: vi.fn(),
    selectSession: vi.fn(),
    resetSession: vi.fn(),
    toggleSession: vi.fn(),
  }),
}))

vi.mock('../services/api', () => ({
  getSessions: vi.fn().mockResolvedValue({ sessions: [] }),
  getSessionMessages: vi.fn().mockResolvedValue({ turns: [], status: 'idle' }),
  sendChat: vi.fn(),
  cancelSession: vi.fn(),
  deleteSession: vi.fn(),
  renameSession: vi.fn(),
  handleApiError: vi.fn(() => ''),
}))

afterEach(cleanup)
beforeEach(() => localStorage.clear())

describe('WorkspacePage panel interactions', () => {
  it('shows the right panel with tabs and a collapse button by default', () => {
    render(<ControlledWorkspace />)
    expect(screen.getByRole('button', { name: '收起执行面板' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '执行轨迹' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '关键证据' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '决策记录' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '资源' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '展开执行面板' })).not.toBeInTheDocument()
  })

  it('collapses the right panel and reveals the edge reopen tab', async () => {
    render(<ControlledWorkspace />)
    await userEvent.click(screen.getByRole('button', { name: '收起执行面板' }))
    expect(screen.queryByRole('button', { name: '收起执行面板' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '执行轨迹' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '展开执行面板' })).toBeInTheDocument()
  })

  it('reopens the right panel from the edge tab', async () => {
    render(<ControlledWorkspace />)
    await userEvent.click(screen.getByRole('button', { name: '收起执行面板' }))
    await userEvent.click(screen.getByRole('button', { name: '展开执行面板' }))
    expect(screen.getByRole('button', { name: '收起执行面板' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '执行轨迹' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '展开执行面板' })).not.toBeInTheDocument()
  })

  it('keeps the left sidebar always expanded with no edge handle', () => {
    render(<ControlledWorkspace />)
    expect(screen.getByRole('button', { name: '新建任务' })).toBeInTheDocument()
    expect(document.querySelector('.panel-edge-handle')).toBeNull()
    expect(document.querySelector('.left-panel-shell.expanded')).not.toBeNull()
  })
})
