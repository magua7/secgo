import { describe, expect, it } from 'vitest'
import { executionReducer, initialExecutionState } from './executionReducer'

describe('executionReducer', () => {
  it('streams a report and auto-collapses when the engine completes', () => {
    let state = executionReducer(initialExecutionState, { type: 'engine:start', data: { session_id: 's1', user_input: 'check' } })
    state = executionReducer(state, { type: 'agent:thinking', data: { session_id: 's1', agent_id: 'operator' } })
    state = executionReducer(state, { type: 'llm:stream', data: { session_id: 's1', agent_id: 'operator', chunk: '# 结论\n高风险' } })
    state = executionReducer(state, { type: 'engine:end', data: { session_id: 's1', reason: 'completed', total_steps: 4 } })
    expect(state.status).toBe('completed')
    expect(state.activeAgent).toBe('operator')
    expect(state.report).toContain('高风险')
    expect(state.executionExpanded).toBe(false)
  })

  it('tracks handoffs, tools, todos and evidence without exposing thinking text', () => {
    let state = executionReducer(initialExecutionState, { type: 'agent:thinking', data: { session_id: 's1', agent_id: 'research' } })
    state = executionReducer(state, { type: 'agent:switch', data: { session_id: 's1', from_agent_id: 'research', to_agent_id: 'operator', reason: '验证情报' } })
    state = executionReducer(state, { type: 'tool:stream-start', data: { session_id: 's1', tool_name: 'VirusTotal', args: { domain: 'example.com' } } })
    state = executionReducer(state, { type: 'tool:stream-end', data: { session_id: 's1', tool_name: 'VirusTotal', result: 'malicious: 3' } })
    state = executionReducer(state, { type: 'todo:updated', data: { session_id: 's1', todo_list: [{ text: '验证证据', done: true }] } })
    expect(state.timeline.some((item) => item.kind === 'handoff')).toBe(true)
    expect(state.tools[0]?.status).toBe('completed')
    expect(state.evidence[0]?.summary).toContain('malicious')
    expect(state.tasks[0]?.done).toBe(true)
    expect(state.completedSteps).toContain('验证证据')
    expect(state.keyFindings[0]).toContain('VirusTotal')
    expect(state.keyProgress.length).toBeGreaterThan(0)
  })

  it('unlocks an awaiting or cancelled execution', () => {
    let waiting = executionReducer(initialExecutionState, { type: 'llm:stream', data: { session_id: 's1', agent_id: 'planner', chunk: '请补充目标地址。' } })
    waiting = executionReducer(waiting, { type: 'engine:awaiting_input', data: { session_id: 's1', agent_id: 'planner', message: '请补充目标地址。' } })
    const cancelled = executionReducer(waiting, { type: 'engine:end', data: { session_id: 's1', reason: 'cancelled', total_steps: 1 } })
    expect(waiting.status).toBe('awaiting_input')
    expect(waiting.phase).toBe('awaiting_user')
    expect(waiting.assistantReply).toBe('请补充目标地址。')
    expect(cancelled.status).toBe('cancelled')
    expect(cancelled.phase).toBe('stopped')
    expect(cancelled.finalAnswer).toContain('本次执行已停止')
  })

  it('keeps a direct planner reply out of task execution state', () => {
    let state = executionReducer(initialExecutionState, { type: 'engine:start', data: { session_id: 's1', user_input: '你好' } })
    state = executionReducer(state, { type: 'agent:thinking', data: { session_id: 's1', agent_id: 'planner' } })
    state = executionReducer(state, { type: 'llm:stream', data: { session_id: 's1', agent_id: 'planner', chunk: '你好，我是 SEC-GO。' } })
    state = executionReducer(state, { type: 'engine:awaiting_input', data: { session_id: 's1', agent_id: 'planner', message: '你好，我是 SEC-GO。' } })
    expect(state.phase).toBe('awaiting_user')
    expect(state.assistantReply).toBe('你好，我是 SEC-GO。')
    expect(state.tasks).toHaveLength(0)
    expect(state.tools).toHaveLength(0)
  })

  it('keeps task execution expanded until reporting and guarantees a completed fallback', () => {
    let state = executionReducer(initialExecutionState, { type: 'engine:start', data: { session_id: 's1', user_input: 'check' } })
    state = executionReducer(state, { type: 'todo:updated', data: { session_id: 's1', todo_list: [{ text: '侦察', done: false }] } })
    state = executionReducer(state, { type: 'tool:stream-start', data: { session_id: 's1', tool_name: 'port_scan', args: {} } })
    expect(state.phase).toBe('executing')
    expect(state.executionExpanded).toBe(true)
    state = executionReducer(state, { type: 'tool:stream-end', data: { session_id: 's1', tool_name: 'port_scan', result: '443 open' } })
    state = executionReducer(state, { type: 'engine:end', data: { session_id: 's1', reason: 'completed', total_steps: 2 } })
    expect(state.phase).toBe('completed')
    expect(state.executionExpanded).toBe(false)
    expect(state.finalAnswer).toContain('未生成完整最终报告')
  })

  it('uses the builder user-facing stream as the final answer without collapsing before reporting', () => {
    let state = executionReducer(initialExecutionState, { type: 'todo:updated', data: { session_id: 's1', todo_list: [{ text: '生成报告', done: false }] } })
    state = executionReducer(state, { type: 'agent:thinking', data: { session_id: 's1', agent_id: 'builder' } })
    state = executionReducer(state, { type: 'llm:stream', data: { session_id: 's1', agent_id: 'builder', chunk: '# 最终报告' } })
    expect(state.phase).toBe('reporting')
    expect(state.finalAnswer).toBe('# 最终报告')
    state = executionReducer(state, { type: 'engine:end', data: { session_id: 's1', reason: 'completed', total_steps: 3 } })
    expect(state.finalAnswer).toBe('# 最终报告')
  })

  it('does not carry an intermediate tool-call stream into the final report', () => {
    let state = executionReducer(initialExecutionState, { type: 'llm:stream', data: { session_id: 's1', agent_id: 'research', chunk: '中间检索说明' } })
    state = executionReducer(state, { type: 'tool:stream-start', data: { session_id: 's1', tool_name: 'dns_lookup', args: {} } })
    expect(state.report).toBe('')
    state = executionReducer(state, { type: 'agent:thinking', data: { session_id: 's1', agent_id: 'builder' } })
    state = executionReducer(state, { type: 'llm:stream', data: { session_id: 's1', agent_id: 'builder', chunk: '# 最终报告' } })
    expect(state.report).toBe('# 最终报告')
  })

  it('deduplicates stream-end and tool-result for the same backend call', () => {
    let state = executionReducer(initialExecutionState, { type: 'tool:stream-start', data: { session_id: 's1', tool_name: 'dns_lookup', args: {} } })
    state = executionReducer(state, { type: 'tool:stream-end', data: { session_id: 's1', tool_name: 'dns_lookup', result: '1.2.3.4' } })
    state = executionReducer(state, { type: 'tool:result', data: { session_id: 's1', tool_name: 'dns_lookup', result: '1.2.3.4' } })
    expect(state.tools).toHaveLength(1)
    expect(state.evidence).toHaveLength(1)
  })

  it('archives readable narrative before a later SSE boundary clears the stream buffer', () => {
    let state = executionReducer(initialExecutionState, { type: 'llm:stream', data: { session_id: 's1', agent_id: 'operator', chunk: '系统特征显示为 ASP.NET MVC 框架，继续验证未授权接口。' } })
    state = executionReducer(state, { type: 'tool:stream-start', data: { session_id: 's1', agent_id: 'operator', tool_name: 'execute_bash', args: {} } })
    expect(state.report).toBe('')
    expect(state.narrativeUpdates.map((item) => item.text)).toContain('系统特征显示为 ASP.NET MVC 框架，继续验证未授权接口。')
  })

  it('never discards an earlier narrative when many later updates arrive', () => {
    let state = initialExecutionState
    for (let index = 0; index < 10; index += 1) {
      state = executionReducer(state, { type: 'llm:stream', data: { session_id: 's1', agent_id: 'operator', chunk: `第 ${index + 1} 条可读进展` } })
      state = executionReducer(state, { type: 'tool:stream-start', data: { session_id: 's1', agent_id: 'operator', tool_name: `tool-${index}`, args: {} } })
    }
    expect(state.narrativeUpdates.map((item) => item.text)).toContain('第 1 条可读进展')
    expect(state.narrativeUpdates).toHaveLength(10)
  })

  it('persists a readable non-builder stream immediately and updates the same narration entry', () => {
    let state = executionReducer(initialExecutionState, { type: 'engine:start', data: { session_id: 's1', user_input: 'check' } })
    state = executionReducer(state, { type: 'agent:thinking', data: { session_id: 's1', agent_id: 'operator' } })
    state = executionReducer(state, { type: 'llm:stream', data: { session_id: 's1', agent_id: 'operator', chunk: '正在读取登录模块' } })
    expect(state.narrativeUpdates).toHaveLength(1)
    expect(state.narrativeUpdates[0]).toMatchObject({ agent: 'operator', text: '正在读取登录模块' })
    state = executionReducer(state, { type: 'llm:stream', data: { session_id: 's1', agent_id: 'operator', chunk: '并分析认证流程。' } })
    expect(state.narrativeUpdates).toHaveLength(1)
    expect(state.narrativeUpdates[0]?.text).toBe('正在读取登录模块并分析认证流程。')
  })

  it('does not promote raw JSON, tool output, system prompts or handoff prompts to live narration', () => {
    const rawSamples = [
      '{"success":true,"output":"raw"}',
      '[工具结果 execute_bash]: raw output',
      '[系统提示：你已执行 20 步。]',
      '[Handoff from Planner]: internal instructions',
    ]
    let state = initialExecutionState
    rawSamples.forEach((text, index) => {
      state = executionReducer(state, { type: 'engine:text', data: { session_id: 's1', agent_id: 'operator', text: `${index ? '' : ''}${text}` } })
    })
    expect(state.narrativeUpdates).toHaveLength(0)
  })

  it('keeps stopped and failed task summaries expanded with prior narration and progress', () => {
    let running = executionReducer(initialExecutionState, { type: 'engine:start', data: { session_id: 's1', user_input: 'check' } })
    running = executionReducer(running, { type: 'todo:updated', data: { session_id: 's1', todo_list: [{ text: '侦察', done: true }] } })
    running = executionReducer(running, { type: 'agent:thinking', data: { session_id: 's1', agent_id: 'operator' } })
    running = executionReducer(running, { type: 'llm:stream', data: { session_id: 's1', agent_id: 'operator', chunk: '已完成基础指纹识别。' } })
    const stopped = executionReducer(running, { type: 'engine:end', data: { session_id: 's1', reason: 'cancelled', total_steps: 3 } })
    expect(stopped.executionExpanded).toBe(true)
    expect(stopped.currentActivity).toBe('operator 正在执行')
    expect(stopped.narrativeUpdates.some((item) => item.text.includes('已完成基础指纹识别'))).toBe(true)
    expect(stopped.completedSteps).toContain('侦察')

    const failed = executionReducer(running, { type: 'engine:error', data: { session_id: 's1', agent_id: 'operator', error: '上游连接失败' } })
    expect(failed.executionExpanded).toBe(true)
    expect(failed.endedAt).not.toBeNull()
    expect(failed.narrativeUpdates.some((item) => item.text.includes('已完成基础指纹识别'))).toBe(true)
    expect(failed.completedSteps).toContain('侦察')
  })

  it('derives persistent human-readable progress from real tool results', () => {
    let state = executionReducer(initialExecutionState, { type: 'tool:stream-start', data: { session_id: 's1', tool_name: 'execute_bash', args: {} } })
    state = executionReducer(state, { type: 'tool:stream-end', data: { session_id: 's1', tool_name: 'execute_bash', result: 'Server: nginx; GET /robots.txt 200; /admin 200; /login 200; ASP.NET MVC' } })
    expect(state.keyProgress.join(' ')).toContain('ASP.NET MVC')
    expect(state.keyProgress.join(' ')).toContain('/admin')
    state = executionReducer(state, { type: 'engine:end', data: { session_id: 's1', reason: 'completed', total_steps: 3 } })
    state = executionReducer(state, { type: 'ui:toggle-execution', data: {} })
    expect(state.keyProgress.join(' ')).toContain('/admin')
  })
})
