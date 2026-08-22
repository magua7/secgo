import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ExecutionTraceViewModel } from '../../types/executionTrace'
import { RightPanel } from './RightPanel'

afterEach(cleanup)

describe('RightPanel', () => {
  it('renders historical execution as a neutral read-only replay without fake identity or time', () => {
    const view: ExecutionTraceViewModel = {
      mode: 'history-readonly', kind: 'agent_task', status: 'idle', activeAgent: 'agent',
      timeline: [{ id: 'h1', at: null, kind: 'tool', title: '工具输出 · curl', detail: 'HTTP 200' }],
      evidence: [], resources: [], notice: '历史数据只读',
    }
    render(<RightPanel view={view} tab="trace" onTabChange={vi.fn()} />)
    expect(screen.getByText('历史执行回放')).toBeInTheDocument()
    expect(screen.getByText('只读')).toBeInTheDocument()
    expect(screen.queryByText('Planner')).not.toBeInTheDocument()
    expect(screen.queryByText('—')).not.toBeInTheDocument()
    expect(screen.getByText('HTTP 200').tagName).toBe('PRE')
    expect(screen.getByText('查看原始输出').closest('details')).not.toHaveAttribute('open')
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
      mode: 'history-readonly', kind: 'empty', status: 'idle', activeAgent: 'agent',
      timeline: [], evidence: [], resources: [], notice: null,
    }
    render(<RightPanel view={view} tab="trace" onTabChange={vi.fn()} />)
    expect(screen.getAllByText('尚未开始任务').length).toBeGreaterThan(0)
    expect(screen.getByText(/提交安全任务后/)).toBeInTheDocument()
    expect(screen.queryByText('本轮为直接回复')).not.toBeInTheDocument()
  })
})
