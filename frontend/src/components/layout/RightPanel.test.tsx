import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ExecutionTraceViewModel } from '../../types/executionTrace'
import { RightPanel } from './RightPanel'

afterEach(cleanup)

describe('RightPanel', () => {
  it('renders snapshot history with the same trace UI plus a light history badge', () => {
    const view: ExecutionTraceViewModel = {
      mode: 'history', kind: 'agent_task', status: 'completed', activeAgent: 'builder',
      timeline: [{ id: 'h1', at: 1000, kind: 'tool', title: '调用 web_search', detail: 'HTTP 200', status: 'completed' }],
      evidence: [{ id: 'e1', type: 'finding', title: '网页搜索结果', source: 'web_search', summary: 'found' }],
      resources: [{ name: 'web_search', count: 1, invocations: [{ name: 'web_search', status: 'completed', result: 'found' }] }],
      notice: null,
    }
    render(<RightPanel view={view} tab="trace" onTabChange={vi.fn()} />)
    expect(screen.getByText('历史记录')).toBeInTheDocument()
    expect(screen.getByText('调用 web_search')).toBeInTheDocument()
    expect(screen.getByText('HTTP 200').tagName).toBe('P')
  })

  it('uses the shared empty state for a direct response', () => {
    const view: ExecutionTraceViewModel = {
      mode: 'live', kind: 'direct_response', status: 'idle', activeAgent: 'planner',
      timeline: [], evidence: [], resources: [], notice: null,
    }
    render(<RightPanel view={view} tab="trace" onTabChange={vi.fn()} />)
    expect(screen.getByText('本轮为直接回复')).toBeInTheDocument()
    expect(screen.getByText('未触发 Agent 执行或工具调用。')).toBeInTheDocument()
    expect(screen.getByText('Planner')).toBeInTheDocument()
  })

  it('distinguishes a new task from a direct response', () => {
    const view: ExecutionTraceViewModel = {
      mode: 'live', kind: 'empty', status: 'idle', activeAgent: 'planner',
      timeline: [], evidence: [], resources: [], notice: null,
    }
    render(<RightPanel view={view} tab="trace" onTabChange={vi.fn()} />)
    expect(screen.getAllByText('尚未开始任务').length).toBeGreaterThan(0)
    expect(screen.getByText(/提交安全任务后/)).toBeInTheDocument()
    expect(screen.queryByText('本轮为直接回复')).not.toBeInTheDocument()
  })

  it('renders a collapse button in the tabs row that invokes onCollapse', async () => {
    const onCollapse = vi.fn()
    const view: ExecutionTraceViewModel = {
      mode: 'live', kind: 'empty', status: 'idle', activeAgent: 'planner',
      timeline: [], evidence: [], resources: [], notice: null,
    }
    render(<RightPanel view={view} tab="trace" onTabChange={vi.fn()} onCollapse={onCollapse} />)
    const collapse = screen.getByRole('button', { name: '收起执行面板' })
    expect(collapse).toBeInTheDocument()
    await userEvent.click(collapse)
    expect(onCollapse).toHaveBeenCalledTimes(1)
  })

  it('keeps the three tabs in a tablist and the collapse button outside it', () => {
    const view: ExecutionTraceViewModel = {
      mode: 'live', kind: 'empty', status: 'idle', activeAgent: 'planner',
      timeline: [], evidence: [], resources: [], notice: null,
    }
    render(<RightPanel view={view} tab="trace" onTabChange={vi.fn()} onCollapse={vi.fn()} />)
    const tablist = screen.getByRole('tablist')
    const tabs = screen.getAllByRole('button', { name: /执行轨迹|证据|资源/ })
    expect(tabs).toHaveLength(3)
    tabs.forEach((tab) => expect(tablist).toContainElement(tab))
    expect(tablist).not.toContainElement(screen.getByRole('button', { name: '收起执行面板' }))
  })

  it('keeps the collapse control in the tabs row, not the scrollable content', () => {
    const view: ExecutionTraceViewModel = {
      mode: 'live', kind: 'agent_task', status: 'running', activeAgent: 'operator',
      timeline: [], evidence: [], resources: [], notice: null,
    }
    render(<RightPanel view={view} tab="trace" onTabChange={vi.fn()} onCollapse={vi.fn()} />)
    const collapse = screen.getByRole('button', { name: '收起执行面板' })
    expect(collapse.closest('.right-tabs-row')).not.toBeNull()
    expect(collapse.closest('.right-content')).toBeNull()
  })

  it('shows the collapse control across direct/empty/running content states', () => {
    const states: ExecutionTraceViewModel[] = [
      { mode: 'live', kind: 'direct_response', status: 'idle', activeAgent: 'planner', timeline: [], evidence: [], resources: [], notice: null },
      { mode: 'live', kind: 'empty', status: 'idle', activeAgent: 'planner', timeline: [], evidence: [], resources: [], notice: null },
      { mode: 'live', kind: 'agent_task', status: 'running', activeAgent: 'operator', timeline: [], evidence: [], resources: [], notice: null },
    ]
    for (const view of states) {
      const { unmount } = render(<RightPanel view={view} tab="trace" onTabChange={vi.fn()} onCollapse={vi.fn()} />)
      expect(screen.getByRole('button', { name: '收起执行面板' })).toBeInTheDocument()
      unmount()
    }
  })
})
