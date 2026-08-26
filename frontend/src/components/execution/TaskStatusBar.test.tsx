import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { TaskStatusBar } from './TaskStatusBar'

afterEach(cleanup)

const base = { elapsedMs: 90_000, toolCount: 46, evidenceCount: 31 }

describe('TaskStatusBar', () => {
  it('shows running/executing status, agent, activity and elapsed', () => {
    render(<TaskStatusBar status="running" phase="executing" activeAgent="operator" currentActivity="正在验证认证接口权限边界" {...base} />)
    expect(screen.getByText('● 正在验证')).toBeInTheDocument()
    expect(screen.getByText('operator')).toBeInTheDocument()
    expect(screen.getByText('正在验证认证接口权限边界')).toBeInTheDocument()
    expect(screen.getByText('01:30')).toBeInTheDocument()
  })

  it('shows planning status and a conservative activity fallback', () => {
    render(<TaskStatusBar status="running" phase="planning" activeAgent="planner" currentActivity="" {...base} />)
    expect(screen.getByText('● 正在规划')).toBeInTheDocument()
    expect(screen.getByText('正在分析任务目标')).toBeInTheDocument()
  })

  it('shows awaiting_user status', () => {
    render(<TaskStatusBar status="awaiting_input" phase="awaiting_user" activeAgent="planner" currentActivity="" {...base} />)
    expect(screen.getByText('● 等待补充')).toBeInTheDocument()
  })

  it('shows a completed terminal summary with stats', () => {
    render(<TaskStatusBar status="completed" phase="completed" activeAgent="builder" currentActivity="" {...base} />)
    expect(screen.getByText('研判完成')).toBeInTheDocument()
    expect(screen.getByText('46 Tools · 31 Evidence')).toBeInTheDocument()
    expect(screen.getByText('01:30')).toBeInTheDocument()
  })

  it('shows a stopped terminal summary', () => {
    render(<TaskStatusBar status="cancelled" phase="stopped" activeAgent="operator" currentActivity="" {...base} />)
    expect(screen.getByText('任务已停止')).toBeInTheDocument()
  })

  it('shows an error terminal summary', () => {
    render(<TaskStatusBar status="error" phase="error" activeAgent="operator" currentActivity="" {...base} />)
    expect(screen.getByText('执行失败')).toBeInTheDocument()
    expect(screen.getByText('46 Tools · 31 Evidence')).toBeInTheDocument()
  })
})
