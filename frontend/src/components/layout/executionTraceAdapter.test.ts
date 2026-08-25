import { describe, expect, it } from 'vitest'
import { historyMessagesToTrace, liveExecutionToTrace } from './executionTraceAdapter'
import { initialExecutionState } from '../../state/executionReducer'

describe('execution trace adapters', () => {
  it('uses one view model shape for live and history replay', () => {
    const live = liveExecutionToTrace({
      ...initialExecutionState,
      status: 'running',
      tasks: [{ text: '侦察', done: false }],
      tools: [{ name: 'port_scan', status: 'completed', result: '443 open' }],
    })
    const history = historyMessagesToTrace([
      { kind: 'user', text: '检查 example.com' },
      { kind: 'assistant', text: '正在侦察' },
      { kind: 'tool', text: '[工具结果] 443 open' },
    ], [{ text: '侦察', done: false }])
    expect(live.mode).toBe('live')
    expect(history.mode).toBe('history-readonly')
    expect(live.kind).toBe('agent_task')
    expect(history.kind).toBe('agent_task')
    expect(history.timeline[0]?.at).toBeNull()
    expect(history.notice).toContain('部分历史执行细节未保存')
    expect(history.resources).toHaveLength(0)
    expect(history.evidence).toHaveLength(0)
  })

  it('recovers fallback user-role tool output as generic trace text, not evidence', () => {
    const view = historyMessagesToTrace([
      { kind: 'user', text: '检查 example.com' },
      { kind: 'assistant', text: '先规划' },
      { kind: 'user', text: '[工具结果 execute_bash]: 443 open' },
      { kind: 'user', text: '[Handoff from Planner]: 继续验证' },
    ], [])
    expect(view.kind).toBe('agent_task')
    expect(view.timeline.map((item) => item.title)).toContain('工具输出 · execute_bash')
    expect(view.timeline.map((item) => item.title)).toContain('已保存的内部交接文本')
    expect(view.evidence).toHaveLength(0)
  })

  it('normalizes escaped newlines and caps oversized historical raw output', () => {
    const raw = `[工具结果 execute_bash]: first\\nsecond ${'x'.repeat(30_000)}`
    const view = historyMessagesToTrace([
      { kind: 'user', text: '检查 example.com' },
      { kind: 'tool', text: raw },
    ], [])
    const item = view.timeline[0]
    expect(item?.title).toBe('工具输出 · execute_bash')
    expect(item?.detail).toContain('first\nsecond')
    expect(item?.detail).not.toContain('first\\nsecond')
    expect(item?.detail?.length).toBeLessThan(13_000)
    expect(item?.detail).toContain('内容过长，已截断')
  })

  it('safely unwraps JSON-stringified output text without rendering escaped newlines', () => {
    const view = historyMessagesToTrace([
      { kind: 'user', text: '检查 example.com' },
      { kind: 'tool', text: '[工具结果 execute_bash]: {"success":true,"output":"hello\\nworld"}' },
    ], [])
    expect(view.timeline[0]?.detail).toBe('hello\nworld')
  })

  it('marks a direct history reply without inventing a trace', () => {
    const view = historyMessagesToTrace([
      { kind: 'user', text: '你好' },
      { kind: 'assistant', text: '你好，我是 SEC-GO。' },
    ], [])
    expect(view.kind).toBe('direct_response')
    expect(view.timeline).toHaveLength(0)
  })

  it('scopes replay to the latest turn or an explicitly selected historical turn', () => {
    const messages = [
      { kind: 'user' as const, text: '检查 example.com' },
      { kind: 'assistant' as const, text: '正在侦察' },
      { kind: 'tool' as const, text: '[工具结果 execute_bash]: HTTP 200' },
      { kind: 'user' as const, text: '你好' },
      { kind: 'assistant' as const, text: '你好，我是 SEC-GO。' },
    ]

    expect(historyMessagesToTrace(messages, []).kind).toBe('direct_response')
    const firstTurn = historyMessagesToTrace(messages, [], 'history-turn-0')
    expect(firstTurn.kind).toBe('agent_task')
    expect(firstTurn.timeline.map((item) => item.title)).toContain('工具输出 · execute_bash')
  })
})
