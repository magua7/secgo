import type { ExecutionEvent } from '../types/events'
import type { AgentId, EvidenceItem, ExecutionState, NarrativeUpdate, TimelineItem, ToolUse } from '../types/execution'

export const createInitialExecutionState = (): ExecutionState => ({
  status: 'idle', phase: 'idle', activeAgent: 'planner', tasks: [], timeline: [], tools: [], evidence: [],
  findings: [], completedSteps: [], keyFindings: [], narrativeUpdates: [], keyProgress: [], report: '', currentActivity: '', assistantReply: '', finalAnswer: '', lastAssistantOutput: '', lastStreamAgent: null, startedAt: null, endedAt: null, totalSteps: 0, reason: '',
  error: null, executionExpanded: true, connection: 'idle', decisions: [],
})

export const initialExecutionState: ExecutionState = createInitialExecutionState()

const line = (state: ExecutionState, item: Omit<TimelineItem, 'id' | 'at'>): TimelineItem => ({
  ...item,
  id: `${state.timeline.length + 1}-${item.kind}`,
  at: Date.now(),
})

const textResult = (value: unknown): string => {
  if (typeof value === 'string') return value
  try { return JSON.stringify(value) } catch { return String(value ?? '') }
}

const finishTool = (tools: ToolUse[], name: string, result: string): ToolUse[] => {
  let index = -1
  for (let itemIndex = tools.length - 1; itemIndex >= 0; itemIndex -= 1) {
    const tool = tools[itemIndex]
    if (tool?.name === name && tool.status === 'running') { index = itemIndex; break }
  }
  if (index < 0) return [...tools, { name, result, status: 'completed' }]
  return tools.map((tool, itemIndex) => itemIndex === index ? { ...tool, result, status: 'completed' } : tool)
}

const appendUnique = (items: string[], value: string) => value && !items.includes(value) ? [...items, value] : items
const appendMany = (items: string[], values: string[]) => values.reduce(appendUnique, items)

const readableNarrative = (value: string): string => {
  const text = value.replace(/\s+/g, ' ').trim()
  if (!text) return ''
  if (/^(?:\{|\[\s*\{)/u.test(text)) return ''
  if (/^\[(?:工具结果|系统提示|Handoff from)(?:[:：\s\]])/iu.test(text)) return ''
  if (/^(?:```|#\s*SKILL\b)/iu.test(text) || /zhiyugo:contract|workflow Catalog/iu.test(text)) return ''
  return text.length > 360 ? `${text.slice(0, 360)}…` : text
}

const appendNarrative = (items: NarrativeUpdate[], value: string, agent: AgentId, timestamp = Date.now()): NarrativeUpdate[] => {
  const text = readableNarrative(value)
  if (!text || items.some((item) => item.text === text)) return items
  return [...items, { id: `narrative-${items.length + 1}-${timestamp}`, text, agent, timestamp }]
}

const updateStreamNarrative = (state: ExecutionState, value: string, agent: AgentId): NarrativeUpdate[] => {
  const text = readableNarrative(value)
  if (!text) return state.narrativeUpdates
  const last = state.narrativeUpdates.at(-1)
  if (state.report && last?.agent === agent) {
    return [...state.narrativeUpdates.slice(0, -1), { ...last, text }]
  }
  return appendNarrative(state.narrativeUpdates, text, agent)
}

const archiveNarrative = (state: ExecutionState) => {
  if (state.lastStreamAgent === 'builder') return state.narrativeUpdates
  return appendNarrative(state.narrativeUpdates, state.report, state.lastStreamAgent ?? state.activeAgent)
}
const capabilityLabels = (text: string) => {
  const labels: string[] = []
  if (/web|recon|侦察/i.test(text)) labels.push('Web 侦察')
  if (/auth|认证|authorization/i.test(text)) labels.push('认证与权限验证')
  if (/api/i.test(text)) labels.push('API 侦察')
  return [...new Set(labels)]
}
const progressFromTool = (name: string, result: string) => {
  const progress: string[] = []
  const labels = capabilityLabels(`${name} ${result}`)
  if (name === 'skill_list') progress.push(labels.length ? `已匹配${labels.join('、')}能力` : '已匹配当前任务所需安全能力')
  if (name === 'skill_read') progress.push(labels.length ? `已加载${labels.join('、')}执行指引` : '已加载所选安全测试执行指引')
  if (/asp\.net\s*(mvc)?/i.test(result)) progress.push('已识别目标使用 ASP.NET MVC 技术栈')
  const endpoints = ['/admin', '/login', '/api', '/swagger', '/actuator'].filter((path) => result.toLowerCase().includes(path))
  if (endpoints.length) progress.push(`发现 ${endpoints.join('、')} 等入口`)
  if (/robots\.txt/i.test(result) || /server\s*:/i.test(result) || /x-powered-by/i.test(result)) progress.push('已获取 robots.txt、HTTP 响应头或页面技术特征')
  const malicious = result.match(/malicious\s*[:=]\s*(\d+)/i)
  if (malicious) progress.push(`${name} 检出 ${malicious[1]} 个恶意判定`)
  return progress
}
export function executionReducer(state: ExecutionState, event: ExecutionEvent): ExecutionState {
  switch (event.type) {
    case 'ui:reset': return createInitialExecutionState()
    case 'ui:toggle-execution': return { ...state, executionExpanded: !state.executionExpanded }
    case 'ui:connection': return { ...state, connection: event.data.connection }
    case 'engine:start':
      return {
        ...initialExecutionState, status: 'running', phase: 'planning', currentActivity: 'Planner 正在规划执行路径', startedAt: Date.now(), connection: state.connection,
        timeline: [line(initialExecutionState, { kind: 'status', title: '任务已创建', status: 'running' })],
      }
    case 'agent:thinking': {
      const agent = event.data.agent_id ?? state.activeAgent
      const reporting = agent === 'builder'
      return { ...state, status: 'running', phase: reporting ? 'reporting' : agent === 'planner' ? 'planning' : 'executing', activeAgent: agent, currentActivity: reporting ? 'Builder 正在生成最终报告' : `${agent} 正在执行`, narrativeUpdates: archiveNarrative(state), report: '', assistantReply: '', executionExpanded: reporting ? false : true, timeline: [...state.timeline, line(state, { kind: 'agent', agent, title: `${agent} 正在执行`, status: 'running' })] }
    }
    case 'agent:switch': {
      const agent = event.data.to_agent_id ?? state.activeAgent
      const action = `已将${event.data.reason ? `${event.data.reason}相关工作` : '当前阶段任务'}移交 ${agent}`
      return { ...state, phase: agent === 'builder' ? 'reporting' : 'executing', activeAgent: agent, currentActivity: `${event.data.from_agent_id ?? 'agent'} 已移交 ${agent}`, executionExpanded: agent === 'builder' ? false : true, keyProgress: appendUnique(state.keyProgress, action), timeline: [...state.timeline, line(state, { kind: 'handoff', agent, title: `${event.data.from_agent_id ?? 'agent'} → ${agent}`, detail: event.data.reason })] }
    }
    case 'tool:call':
    case 'tool:stream-start': {
      const name = event.data.tool_name ?? '未知工具'
      if (state.tools.some((tool) => tool.name === name && tool.status === 'running')) return state
      return {
        ...state,
        phase: 'executing', currentActivity: `${state.activeAgent} 正在调用 ${name}`, executionExpanded: true,
        narrativeUpdates: archiveNarrative(state), report: '', assistantReply: '', finalAnswer: '',
        tools: [...state.tools, { name, args: event.data.args, status: 'running' }],
        timeline: [...state.timeline, line(state, { kind: 'tool', agent: event.data.agent_id ?? state.activeAgent, title: `调用 ${name}`, status: 'running' })],
      }
    }
    case 'tool:result':
    case 'tool:stream-end': {
      const name = event.data.tool_name ?? '未知工具'
      const result = textResult(event.data.result).slice(0, 1200)
      const duplicate = event.type === 'tool:result' && state.tools.some((tool) => tool.name === name && tool.status === 'completed' && tool.result === result)
      if (duplicate) return state
      return {
        ...state,
        phase: 'executing', currentActivity: `${name} 已完成`, executionExpanded: true,
        tools: finishTool(state.tools, name, result),
        // Evidence 只来自显式 engine:evidence 事件，普通 Tool Result 不再自动进入 Evidence
        keyFindings: appendMany(state.keyFindings, progressFromTool(name, result).filter((item) => item.startsWith('已识别') || item.startsWith('发现') || item.includes('检出'))),
        keyProgress: appendMany(state.keyProgress, progressFromTool(name, result)),
        timeline: [...state.timeline, line(state, { kind: 'tool', agent: event.data.agent_id ?? state.activeAgent, title: `${name} 已完成`, detail: result.slice(0, 180), status: 'completed' })],
      }
    }
    case 'llm:stream': {
      const agent = event.data.agent_id ?? state.activeAgent
      const report = state.report + (event.data.chunk ?? '')
      const reporting = agent === 'builder'
      return { ...state, phase: reporting ? 'reporting' : state.phase, report, assistantReply: report, lastStreamAgent: agent, finalAnswer: reporting ? report : state.finalAnswer, narrativeUpdates: reporting ? state.narrativeUpdates : updateStreamNarrative(state, report, agent), executionExpanded: reporting ? false : state.executionExpanded }
    }
    case 'engine:text': {
      const text = event.data.text?.trim() ?? ''
      if (!text) return state
      const agent = event.data.agent_id ?? state.activeAgent
      return { ...state, report: state.report || text, assistantReply: text, lastAssistantOutput: text, lastStreamAgent: agent, finalAnswer: agent === 'builder' ? text : state.finalAnswer, narrativeUpdates: agent === 'builder' ? state.narrativeUpdates : appendNarrative(state.narrativeUpdates, text, agent) }
    }
    case 'todo:updated': {
      const tasks = event.data.todo_list ?? []
      const completedSteps = tasks.filter((task) => task.done && !state.tasks.some((old) => old.text === task.text && old.done)).reduce((items, task) => appendUnique(items, task.text), state.completedSteps)
      return { ...state, phase: state.phase === 'executing' || state.phase === 'reporting' ? state.phase : 'planning', currentActivity: state.currentActivity || 'Planner 正在规划执行路径', tasks, completedSteps, executionExpanded: state.phase !== 'reporting' }
    }
    case 'engine:awaiting_input': {
      const assistantReply = event.data.message?.trim() || state.assistantReply || state.report || state.lastAssistantOutput
      return { ...state, status: 'awaiting_input', phase: 'awaiting_user', activeAgent: event.data.agent_id ?? state.activeAgent, assistantReply, timeline: [...state.timeline, line(state, { kind: 'status', title: '等待补充输入', detail: assistantReply })] }
    }
    case 'engine:user_input': return { ...state, status: 'running', phase: state.tasks.length || state.tools.length ? 'executing' : 'planning', assistantReply: '', finalAnswer: '', report: '' }
    case 'budget:exceeded': {
      const detail = `${event.data.usage ?? 0} / ${event.data.limit ?? 0} tokens`
      return { ...state, error: `预算超限：${detail}`, timeline: [...state.timeline, line(state, { kind: 'error', title: '预算超限', detail, status: 'error' })] }
    }
    case 'engine:error': {
      const error = event.data.error ?? '引擎执行失败'
      return { ...state, status: 'error', phase: 'error', error, endedAt: Date.now(), finalAnswer: state.lastAssistantOutput || `任务执行失败：${error}`, narrativeUpdates: appendNarrative(state.narrativeUpdates, `执行失败：${error}`, event.data.agent_id ?? state.activeAgent), executionExpanded: true, timeline: [...state.timeline, line(state, { kind: 'error', title: '执行错误', detail: error, status: 'error' })] }
    }
    case 'engine:evidence': {
      const evidence = event.data.evidence
      if (!evidence) return state
      const exists = state.evidence.some((item) => item.id === evidence.id || (item.source === evidence.source && item.summary === evidence.summary))
      if (exists) return state
      const record: EvidenceItem = {
        id: evidence.id ?? `evidence-${state.evidence.length + 1}`,
        type: evidence.type,
        title: evidence.title,
        source: evidence.source ?? '未知来源',
        summary: evidence.summary ?? '',
        timestamp: evidence.timestamp,
        metadata: evidence.metadata,
      }
      return { ...state, evidence: [...state.evidence, record] }
    }
    case 'decision:reason': {
      const decision = event.data.decision as Record<string, unknown> | undefined
      if (!decision) return state
      const exists = state.decisions.some((d) => d.id === decision.id)
      if (exists) return state
      const record = {
        id: decision.id as string,
        timestamp: decision.timestamp as number,
        trigger: decision.trigger as string,
        trigger_detail: decision.trigger_detail as string,
        observation: decision.observation as string,
        candidates: decision.candidates as any[],
        selected: decision.selected as string,
        reason: decision.reason as string,
        rejected: decision.rejected as string[],
      }
      return {
        ...state,
        decisions: [...state.decisions, record],
        timeline: [...state.timeline, line(state, { kind: 'finding', title: '◆ 策略调整', detail: `${record.trigger_detail} → ${record.reason}`.slice(0, 180), status: 'completed' })],
      }
    }
    case 'persistence:warning':
      return state
    case 'engine:end': {
      const reason = event.data.reason ?? 'completed'
      const status = reason === 'cancelled' ? 'cancelled' : reason === 'completed' ? 'completed' : 'error'
      const phase = status === 'cancelled' ? 'stopped' : status === 'completed' ? 'completed' : 'error'
      const completedFallback = '本次任务已结束，但未生成完整最终报告。\n\n已保留本轮执行进展、工具调用与证据。\n你可以继续提问：“请根据已有结果生成最终报告。”'
const stoppedFallback = '本次执行已停止，当前发现与执行记录已保留。\n\n你可以在右侧执行面板查看记录、继续追问，或要求基于当前结果总结。'
      const finalAnswer = status === 'cancelled'
        ? stoppedFallback
        : state.finalAnswer.trim() || state.report.trim() || state.lastAssistantOutput.trim() || (status === 'completed' ? completedFallback : state.error || '任务执行异常，当前执行记录已保留。')
      const terminalNarrative = status === 'cancelled'
        ? appendNarrative(state.narrativeUpdates, '用户停止了本次执行。', state.activeAgent)
        : status === 'error'
          ? appendNarrative(state.narrativeUpdates, `执行失败：${event.data.error ?? state.error ?? reason}`, state.activeAgent)
          : state.narrativeUpdates
      return {
        ...state, status, phase, reason, finalAnswer, totalSteps: event.data.total_steps ?? 0, endedAt: Date.now(),
        error: event.data.error ?? state.error, narrativeUpdates: terminalNarrative, executionExpanded: status !== 'completed', currentActivity: status === 'completed' ? '研判完成' : state.currentActivity || (status === 'cancelled' ? '执行已由用户停止' : '执行失败'),
        timeline: [...state.timeline, line(state, { kind: 'status', title: status === 'completed' ? '研判完成' : status === 'cancelled' ? '任务已停止' : '任务结束', detail: reason, status: status === 'completed' ? 'completed' : 'error' })],
      }
    }
  }
}