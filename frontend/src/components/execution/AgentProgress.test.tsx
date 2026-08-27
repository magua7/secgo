import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { AgentProgress } from './AgentProgress'

afterEach(cleanup)

function stateClasses(): string[] {
  return [...document.querySelectorAll('.agent-progress .agent-state')].map((node) => node.className)
}

describe('AgentProgress', () => {
  it('labels Builder as 构建, not 报告', () => {
    render(<AgentProgress activeAgent="planner" status="idle" />)
    const text = document.querySelector('.agent-progress')!.textContent ?? ''
    expect(text).toContain('构建')
    expect(text).not.toContain('报告')
  })

  it('only marks actually-participated agents after completion', () => {
    render(<AgentProgress activeAgent="planner" status="completed" participatedAgents={['planner', 'operator']} />)
    const cls = stateClasses()
    expect(cls[0]).toContain('participated')   // planner
    expect(cls[1]).not.toContain('participated') // research 未参与
    expect(cls[2]).toContain('participated')   // operator
    expect(cls[3]).not.toContain('participated') // builder 未参与
  })

  it('highlights only the active agent while running', () => {
    render(<AgentProgress activeAgent="research" status="running" participatedAgents={['planner']} />)
    const cls = stateClasses()
    expect(cls[1]).toContain('active') // research 当前执行
    expect(cls[0]).toContain('participated') // planner 已参与
    expect(cls[0]).not.toContain('active')
  })
})
