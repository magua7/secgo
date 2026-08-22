import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup } from '@testing-library/react'
import { ExecutionBlock } from './ExecutionBlock'
import { historyMessagesToTurns } from './conversationAdapter'
import { initialExecutionState } from '../../state/executionReducer'

describe('ExecutionBlock', () => {
  afterEach(cleanup)
  it('renders a thin completed summary when execution is collapsed', () => {
    const onToggle = vi.fn()
    render(<ExecutionBlock state={{ ...initialExecutionState, status: 'completed', phase: 'completed', totalSteps: 6, executionExpanded: false }} onToggle={onToggle} />)
    expect(screen.getByText(/研判完成/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /查看执行轨迹/ })).not.toBeInTheDocument()
    screen.getByRole('button', { name: /展开/ }).click()
    expect(onToggle).toHaveBeenCalledOnce()
  })

  it('collapses reporting into a truthful final-report transition summary', () => {
    render(<ExecutionBlock state={{ ...initialExecutionState, status: 'running', phase: 'reporting', executionExpanded: false, startedAt: 1_000, endedAt: null }} />)
    expect(screen.getByText(/研判完成，正在生成报告/)).toBeInTheDocument()
  })

  it('shows current activity, the latest four narration items, key progress and stats without a duplicate trace action', () => {
    render(<ExecutionBlock state={{
      ...initialExecutionState,
      status: 'running',
      phase: 'executing',
      activeAgent: 'operator',
      currentActivity: '当前动作',
      keyProgress: Array.from({ length: 10 }, (_, index) => `进展 ${index + 1}`),
      narrativeUpdates: Array.from({ length: 6 }, (_, index) => ({ id: `n${index + 1}`, text: `播报 ${index + 1}`, agent: 'operator', timestamp: Date.UTC(2026, 7, 21, 8, 31, index + 1) })),
      tools: [{ name: 'curl', status: 'completed', result: 'ok' }, { name: 'curl', status: 'completed', result: 'ok2' }],
    }} onToggle={vi.fn()} />)
    expect(screen.getByText('当前活动')).toBeInTheDocument()
    expect(screen.getByText('过程播报')).toBeInTheDocument()
    expect(screen.queryByText('播报 1')).not.toBeInTheDocument()
    expect(screen.queryByText('播报 2')).not.toBeInTheDocument()
    expect(screen.getByText('播报 3')).toBeInTheDocument()
    expect(screen.getByText('播报 6')).toBeInTheDocument()
    expect(screen.getByText('关键进展')).toBeInTheDocument()
    expect(screen.queryByText('进展 1')).not.toBeInTheDocument()
    expect(screen.queryByText('进展 2')).not.toBeInTheDocument()
    expect(screen.getByText('进展 3')).toBeInTheDocument()
    expect(screen.getByText(/进展 10/)).toBeInTheDocument()
    expect(screen.queryByText(/详细执行/)).not.toBeInTheDocument()
    expect(screen.queryByText(/工具调用/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /查看执行轨迹/ })).not.toBeInTheDocument()
  })

  it('shows a phase-derived current activity instead of an empty expanded body', () => {
    render(<ExecutionBlock state={{ ...initialExecutionState, status: 'running', phase: 'executing', activeAgent: 'operator', currentActivity: '' }} />)
    expect(screen.getByText('当前活动')).toBeInTheDocument()
    expect(screen.getByText(/正在执行当前阶段任务/)).toBeInTheDocument()
  })

  it('keeps a stopped task as a full readable summary without calling it completed', () => {
    render(<ExecutionBlock state={{
      ...initialExecutionState,
      status: 'cancelled', phase: 'stopped', executionExpanded: true, currentActivity: 'Operator 正在验证认证接口',
      narrativeUpdates: [{ id: 'n1', text: '已完成初始攻击面识别', agent: 'operator', timestamp: Date.UTC(2026, 7, 21, 8, 31, 9) }],
      keyProgress: ['已识别目标技术栈'],
    }} />)
    expect(screen.getByText('任务已停止')).toBeInTheDocument()
    expect(screen.queryByText('研判完成')).not.toBeInTheDocument()
    expect(screen.getByText(/Operator 正在验证认证接口/)).toBeInTheDocument()
    expect(screen.getByText('过程播报')).toBeInTheDocument()
    expect(screen.getByText('已完成初始攻击面识别')).toBeInTheDocument()
    expect(screen.getByText('已识别目标技术栈')).toBeInTheDocument()
  })

  it('keeps an error task expanded with the progress collected before failure', () => {
    render(<ExecutionBlock state={{
      ...initialExecutionState,
      status: 'error', phase: 'error', executionExpanded: true, error: '上游连接失败', currentActivity: 'Operator 正在检查接口',
      narrativeUpdates: [{ id: 'n1', text: '正在验证接口权限边界', agent: 'operator', timestamp: Date.UTC(2026, 7, 21, 8, 31, 9) }],
      keyProgress: ['已发现登录入口'],
    }} />)
    expect(screen.getByText('执行失败')).toBeInTheDocument()
    expect(screen.getByText('正在验证接口权限边界')).toBeInTheDocument()
    expect(screen.getByText('已发现登录入口')).toBeInTheDocument()
    expect(screen.getByText('上游连接失败')).toBeInTheDocument()
  })

  it('renders markdown in live narration instead of exposing emphasis markers', () => {
    render(<ExecutionBlock state={{
      ...initialExecutionState,
      status: 'running', phase: 'executing', currentActivity: '继续验证',
      narrativeUpdates: [{ id: 'n1', text: '正在进行 **权限验证**', agent: 'operator', timestamp: Date.UTC(2026, 7, 21, 8, 31, 9) }],
    }} />)
    expect(screen.getByText('权限验证').tagName).toBe('STRONG')
    expect(screen.queryByText(/\*\*权限验证\*\*/)).not.toBeInTheDocument()
  })

  it('does not invent a zero evidence count for historical execution', () => {
    const turn = historyMessagesToTurns([
      { kind: 'user', text: '检查 example.com' },
      { kind: 'tool', text: '[工具结果 execute_bash]: ok' },
    ])[0]
    render(<ExecutionBlock presentation={turn?.execution ?? undefined} />)
    expect(screen.queryByText(/0 Evidence|0 证据/)).not.toBeInTheDocument()
  })

  it('restores persisted Agent narration when a historical execution is expanded', () => {
    const turn = historyMessagesToTurns([
      { kind: 'user', text: '检查 example.com' },
      { kind: 'assistant', text: '正在进行 **技术栈识别**' },
      { kind: 'tool', text: '[工具结果 execute_bash]: 443 open' },
    ])[0]
    const presentation = turn?.execution ? { ...turn.execution, expanded: true } : undefined

    render(<ExecutionBlock presentation={presentation} />)

    expect(screen.getByText('当前活动')).toBeInTheDocument()
    expect(screen.getByText('过程播报')).toBeInTheDocument()
    expect(screen.getByText('技术栈识别').tagName).toBe('STRONG')
  })
})
