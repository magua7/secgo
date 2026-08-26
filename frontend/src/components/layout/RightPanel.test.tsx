import { cleanup, render, screen } from '@testing-library/react'
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
})
