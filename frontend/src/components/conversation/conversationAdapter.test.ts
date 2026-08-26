import { describe, expect, it } from 'vitest'
import { liveExecutionToTurn, selectTaskExecution } from './conversationAdapter'
import { executionReducer } from '../../state/executionReducer'
import { initialExecutionState } from '../../state/executionReducer'
import type { PersistedTurn } from '../../types/session'
import type { ExecutionState } from '../../types/execution'

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

const agentSnapshot = (id: string): PersistedTurn['execution'] => ({
  run_id: id, session_id: 's1', turn_id: id,
  status: 'completed', phase: 'completed', reason: 'completed', error: null,
  active_agent: 'builder', started_at: 1000, ended_at: 2000, current_activity: '研判完成',
  narrative_updates: [], key_progress: [], key_findings: [], tasks: [],
  timeline: [{ id: 't1', at: 1000, kind: 'agent', agent: 'planner', title: 'planner 正在执行', status: 'running' }],
  evidence: [], resources: [{ name: 'skill_list', status: 'completed', result: 'r', at: 1000 }],
  final_report: '# 报告', partial_report: null, last_assistant_output: '# 报告',
  tool_count: 1, evidence_count: 0, total_steps: 2,
})

const persistedTurnsFixture: PersistedTurn[] = [
  {
    id: 't1', sequence: 1, kind: 'agent_task',
    userMessage: { text: 'task1', attachments: [] },
    assistantAnswer: '# 报告', execution: agentSnapshot('t1'), status: 'completed',
    createdAt: null, updatedAt: null,
  },
  {
    id: 't2', sequence: 2, kind: 'direct_response',
    userMessage: { text: '你好', attachments: [] },
    assistantAnswer: '你好，我是 SEC-GO。', execution: null, status: 'awaiting_user',
    createdAt: null, updatedAt: null,
  },
]

describe('selectTaskExecution', () => {
  it('hides the status bar when the latest turn is a direct response, even if an earlier turn was an agent task', () => {
    // Turn 1 = completed agent_task, Turn 2 = direct_response (latest). No liveTurn.
    const task = selectTaskExecution(false, null, persistedTurnsFixture)
    expect(task).toBeNull()
  })

  it('uses the latest turn only when it is an agent task with execution (no backwards search)', () => {
    const latestAgent = [...persistedTurnsFixture, {
      id: 't3', sequence: 3, kind: 'agent_task' as const,
      userMessage: { text: 'task2', attachments: [] },
      assistantAnswer: '# 报告', execution: agentSnapshot('t3'), status: 'completed',
      createdAt: null, updatedAt: null,
    }]
    const task = selectTaskExecution(false, null, latestAgent)
    expect(task).not.toBeNull()
    expect(task?.status).toBe('completed')
    expect(task?.activeAgent).toBe('builder')
  })

  it('prefers the live execution when a live turn exists, regardless of an earlier agent task', () => {
    const live: ExecutionState = { ...initialExecutionState, status: 'running', phase: 'executing', activeAgent: 'operator', currentActivity: '正在验证' }
    const task = selectTaskExecution(true, live, persistedTurnsFixture)
    expect(task).toBe(live)
  })

  it('returns the live execution even when it is a direct response (caller filters via hasAgentTaskSignals)', () => {
    const live: ExecutionState = { ...initialExecutionState, status: 'awaiting_input', phase: 'awaiting_user', activeAgent: 'planner' }
    const task = selectTaskExecution(true, live, persistedTurnsFixture)
    expect(task).toBe(live)
  })

  it('returns null when there are no turns', () => {
    expect(selectTaskExecution(false, null, [])).toBeNull()
  })
})
