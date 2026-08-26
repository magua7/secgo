import { describe, expect, it } from 'vitest'
import { liveExecutionToTurn } from './conversationAdapter'
import { executionReducer } from '../../state/executionReducer'
import { initialExecutionState } from '../../state/executionReducer'

describe('conversation adapters', () => {
  it('treats a completed live report as the final answer but running text as activity', () => {
    const running = liveExecutionToTurn('目标', { ...initialExecutionState, status: 'running', tasks: [{ text: '分析', done: false }], currentActivity: '正在分析' })
    const completed = liveExecutionToTurn('目标', { ...initialExecutionState, status: 'completed', phase: 'completed', tasks: [{ text: '分析', done: true }], finalAnswer: '最终结论' })
    expect(running.kind).toBe('agent_task')
    expect(running.finalAnswer).toBeNull()
    expect(running.execution?.currentActivity).toBe('正在分析')
    expect(completed.finalAnswer).toBe('最终结论')
  })

  it('normalizes a direct reply without inventing task execution', () => {
    let state = executionReducer(initialExecutionState, { type: 'engine:start', data: { session_id: 's1', user_input: '你好' } })
    state = executionReducer(state, { type: 'llm:stream', data: { session_id: 's1', agent_id: 'planner', chunk: '你好，我是 SEC-GO。' } })
    state = executionReducer(state, { type: 'engine:awaiting_input', data: { session_id: 's1', agent_id: 'planner', message: '你好，我是 SEC-GO。' } })
    const live = liveExecutionToTurn('你好', state)
    expect(live.kind).toBe('direct_response')
    expect(live.finalAnswer).toBe('你好，我是 SEC-GO。')
    expect(live.execution).toBeNull()
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

  it('does not infer an agent task from assistant identity alone', () => {
    const live = liveExecutionToTurn('你好', { ...initialExecutionState, status: 'awaiting_input', phase: 'awaiting_user', activeAgent: 'research', assistantReply: '普通回复' })
    expect(live.kind).toBe('direct_response')
  })
})
