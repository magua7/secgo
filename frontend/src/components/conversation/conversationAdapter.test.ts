import { describe, expect, it } from 'vitest'
import { commitVisibleLiveTurn, historyMessagesToTurns, liveExecutionToTurn } from './conversationAdapter'
import { executionReducer } from '../../state/executionReducer'
import { initialExecutionState } from '../../state/executionReducer'

describe('conversation adapters', () => {
  it('keeps tool-following handoff and system prompts inside one execution turn', () => {
    const turns = historyMessagesToTurns([
      { kind: 'user', text: '检查 example.com' },
      { kind: 'assistant', text: '先制定计划' },
      { kind: 'tool', text: '[工具结果] {"ok":true}' },
      { kind: 'user', text: '[Handoff from Planner]: 执行侦察' },
      { kind: 'assistant', text: '正在侦察' },
      { kind: 'tool', text: '[工具结果] 发现 443' },
    ])

    expect(turns).toHaveLength(1)
    expect(turns[0]?.userMessage.text).toBe('检查 example.com')
    expect(turns[0]?.finalAnswer).toBeNull()
    expect(turns[0]?.execution?.details).toHaveLength(3)
    expect(turns[0]?.execution?.toolGroups[0]?.count).toBe(2)
  })

  it('keeps fallback tool results and handoffs stored as user text inside one execution turn', () => {
    const turns = historyMessagesToTurns([
      { kind: 'user', text: '检查 example.com' },
      { kind: 'assistant', text: '先制定计划' },
      { kind: 'user', text: '[工具结果 skill_list]: {"ok":true}' },
      { kind: 'user', text: '[Handoff from Planner]: 执行侦察' },
      { kind: 'assistant', text: '正在侦察' },
      { kind: 'user', text: '[工具结果 execute_bash]: 发现 443' },
    ])

    expect(turns).toHaveLength(1)
    expect(turns[0]?.userMessage.text).toBe('检查 example.com')
    expect(turns[0]?.kind).toBe('agent_task')
    expect(turns[0]?.execution?.toolGroups[0]?.count).toBe(2)
    expect(turns[0]?.execution?.evidenceCount).toBeNull()
  })

  it('keeps the backend ten-step system reminder inside the active history turn', () => {
    const turns = historyMessagesToTurns([
      { kind: 'user', text: '检查 example.com' },
      { kind: 'assistant', text: '正在执行' },
      { kind: 'user', text: '[系统提示：你已执行 10 步。如果长时间无进展，考虑总结当前发现并 handoff 给 Planner。]' },
      { kind: 'assistant', text: '继续执行' },
    ])
    expect(turns).toHaveLength(1)
    expect(turns[0]?.kind).toBe('agent_task')
    expect(turns[0]?.execution?.details.some((item) => item.kind === 'system')).toBe(true)
  })

  it('starts a real follow-up turn after a final assistant answer', () => {
    const turns = historyMessagesToTurns([
      { kind: 'user', text: '第一问' },
      { kind: 'assistant', text: '第一答' },
      { kind: 'user', text: '继续检查' },
      { kind: 'assistant', text: '第二答' },
    ])

    expect(turns.map((turn) => turn.userMessage.text)).toEqual(['第一问', '继续检查'])
    expect(turns.map((turn) => turn.finalAnswer)).toEqual(['第一答', '第二答'])
  })

  it('treats a completed live report as the final answer but running text as activity', () => {
    const running = liveExecutionToTurn('目标', { ...initialExecutionState, status: 'running', tasks: [{ text: '分析', done: false }], currentActivity: '正在分析' })
    const completed = liveExecutionToTurn('目标', { ...initialExecutionState, status: 'completed', phase: 'completed', tasks: [{ text: '分析', done: true }], finalAnswer: '最终结论' })
    expect(running.kind).toBe('agent_task')
    expect(running.finalAnswer).toBeNull()
    expect(running.execution?.currentActivity).toBe('正在分析')
    expect(completed.finalAnswer).toBe('最终结论')
  })

  it('normalizes the same direct reply identically for live and history', () => {
    let state = executionReducer(initialExecutionState, { type: 'engine:start', data: { session_id: 's1', user_input: '你好' } })
    state = executionReducer(state, { type: 'llm:stream', data: { session_id: 's1', agent_id: 'planner', chunk: '你好，我是 SEC-GO。' } })
    state = executionReducer(state, { type: 'engine:awaiting_input', data: { session_id: 's1', agent_id: 'planner', message: '你好，我是 SEC-GO。' } })
    const live = liveExecutionToTurn('你好', state)
    const history = historyMessagesToTurns([{ kind: 'user', text: '你好' }, { kind: 'assistant', text: '你好，我是 SEC-GO。' }])[0]
    expect(live.kind).toBe('direct_response')
    expect(history?.kind).toBe('direct_response')
    expect(live.finalAnswer).toBe(history?.finalAnswer)
    expect(live.execution).toBeNull()
    expect(history?.execution).toBeNull()
  })

  it('classifies a turn as an agent task only from structural execution signals', () => {
    const task = liveExecutionToTurn('检查 example.com', {
      ...initialExecutionState,
      status: 'running',
      tasks: [{ text: '侦察', done: false }],
      currentActivity: 'Planner 正在规划执行路径',
    })
    expect(task.kind).toBe('agent_task')
    expect(task.execution?.expanded).toBe(true)
  })

  it('does not infer an agent task from assistant count or agent identity alone', () => {
    const live = liveExecutionToTurn('你好', { ...initialExecutionState, status: 'awaiting_input', phase: 'awaiting_user', activeAgent: 'research', assistantReply: '普通回复' })
    const history = historyMessagesToTurns([
      { kind: 'user', text: '你好' },
      { kind: 'assistant', text: '第一段' },
      { kind: 'assistant', text: '第二段' },
    ])[0]
    expect(live.kind).toBe('direct_response')
    expect(history?.kind).toBe('direct_response')
  })

  it('commits an awaiting live turn before the next user input', () => {
    const awaiting = { ...initialExecutionState, status: 'awaiting_input' as const, phase: 'awaiting_user' as const, assistantReply: '第一答' }
    const committed = commitVisibleLiveTurn([], '第一问', awaiting)
    expect(committed).toHaveLength(1)
    expect(committed[0]?.userMessage.text).toBe('第一问')
    expect(committed[0]?.finalAnswer).toBe('第一答')
  })

  it('keeps the last assistant output visible as a history fallback even when a tool result follows it', () => {
    const turns = historyMessagesToTurns([
      { kind: 'user', text: '检查 example.com' },
      { kind: 'assistant', text: '正在执行' },
      { kind: 'tool', text: '[工具结果] 443 open' },
      { kind: 'assistant', text: '最终报告内容' },
      { kind: 'tool', text: '[工具结果] 任务结束' },
    ], [{ text: '侦察', done: true }])
    expect(turns[0]?.kind).toBe('agent_task')
    expect(turns[0]?.finalAnswer).toBe('最终报告内容')
    expect(turns[0]?.execution?.expanded).toBe(false)
  })
})
