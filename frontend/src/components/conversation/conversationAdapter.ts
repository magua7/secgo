import type { ConversationTurn, DetailedExecutionEntry, ExecutionPresentation, ToolExecutionGroup } from '../../types/conversation'
import type { ConversationPhase, ExecutionState } from '../../types/execution'
import type { HistoryMessage, TodoItem } from '../../types/session'

const groupTools = (entries: Array<{ name: string; text: string }>): ToolExecutionGroup[] => {
  const groups = new Map<string, string[]>()
  entries.forEach(({ name, text }) => groups.set(name, [...(groups.get(name) ?? []), text]))
  return [...groups].map(([name, values]) => ({ name, count: values.length, entries: values }))
}

const unique = (items: string[]) => [...new Set(items.filter(Boolean))]

interface ConversationSignals {
  todoCount?: number
  toolOutputCount?: number
  evidenceCount?: number
  handoffCount?: number
  findingCount?: number
  internalCount?: number
}

export const classifyConversationKind = (signals: ConversationSignals): ConversationTurn['kind'] => (
  (signals.todoCount ?? 0)
  + (signals.toolOutputCount ?? 0)
  + (signals.evidenceCount ?? 0)
  + (signals.handoffCount ?? 0)
  + (signals.findingCount ?? 0)
  + (signals.internalCount ?? 0) > 0 ? 'agent_task' : 'direct_response'
)

export type HistoryMessageSemantic = 'user' | 'assistant' | 'tool_output' | 'handoff' | 'system'

export function historyMessageSemantic(message: HistoryMessage): HistoryMessageSemantic {
  if (message.kind === 'tool' || /^\[工具结果(?:\s+[^\]]+)?\]\s*:?/u.test(message.text)) return 'tool_output'
  if (message.kind === 'user' && /^\[Handoff from [^\]]+\]\s*:/i.test(message.text)) return 'handoff'
  if (message.kind === 'user' && /^\[系统提示：你已执行\s+\d+\s+步。/u.test(message.text)) return 'system'
  return message.kind
}

export function hasAgentTaskSignals(state: ExecutionState): boolean {
  return classifyConversationKind({
    todoCount: state.tasks.length,
    toolOutputCount: state.tools.length,
    evidenceCount: state.evidence.length,
    handoffCount: state.timeline.filter((item) => item.kind === 'handoff').length,
    findingCount: state.timeline.filter((item) => item.kind === 'finding').length,
  }) === 'agent_task'
}

interface NormalizedTurnInput {
  id: string
  userText: string
  phase: ConversationPhase
  hasTaskSignals: boolean
  execution: ExecutionPresentation
  assistantText: string | null
  isFinalStreaming?: boolean
}

export function normalizeConversationTurn(input: NormalizedTurnInput): ConversationTurn {
  const kind = input.hasTaskSignals ? 'agent_task' : 'direct_response'
  return {
    id: input.id,
    kind,
    phase: kind === 'direct_response' && input.phase !== 'awaiting_user' ? 'direct_response' : input.phase,
    userMessage: { text: input.userText },
    execution: kind === 'agent_task' ? input.execution : null,
    finalAnswer: input.assistantText?.trim() || null,
    isFinalStreaming: Boolean(input.isFinalStreaming),
  }
}

const historicalExecution = (messages: HistoryMessage[], todoList: TodoItem[], completed: boolean): ExecutionPresentation => {
  const details: DetailedExecutionEntry[] = messages.filter((message) => historyMessageSemantic(message) !== 'tool_output').map((message, index) => ({
    id: `history-${index}`,
    kind: historyMessageSemantic(message) === 'handoff' || historyMessageSemantic(message) === 'system' ? 'system' : 'narrative',
    text: message.text,
  }))
  const toolEntries = messages.filter((message) => historyMessageSemantic(message) === 'tool_output').map((message) => ({ name: '已保存的工具输出', text: message.text }))
  return {
    source: 'history', status: completed ? 'completed' : 'idle', phase: completed ? 'completed' : 'idle', activeAgent: 'agent', currentActivity: '', keyProgress: [], narrativeUpdates: [], details,
    toolGroups: groupTools(toolEntries), completedTasks: todoList.filter((task) => task.done).length, totalTasks: todoList.length,
    evidenceCount: null, totalSteps: details.length + toolEntries.length, agentCount: details.length ? 1 : 0,
    error: null, expanded: false, elapsedMs: null, startedAt: null, endedAt: null,
  }
}

export function historyMessagesToTurns(messages: HistoryMessage[], todoList: TodoItem[] = []): ConversationTurn[] {
  const starts = messages.reduce<number[]>((items, message, index) => {
    if (historyMessageSemantic(message) === 'user') items.push(index)
    return items
  }, [])
  return starts.map((start, turnIndex) => {
    const end = starts[turnIndex + 1] ?? messages.length
    const segment = messages.slice(start + 1, end)
    const turnTodoList = turnIndex === starts.length - 1 ? todoList : []
    let lastAssistantIndex = -1
    for (let index = segment.length - 1; index >= 0; index -= 1) {
      if (segment[index]?.kind === 'assistant') { lastAssistantIndex = index; break }
    }
    const allTodosDone = turnTodoList.length > 0 && turnTodoList.every((task) => task.done)
    const canUseFinalAssistant = lastAssistantIndex >= 0 && (lastAssistantIndex === segment.length - 1 || allTodosDone)
    const finalAnswer = canUseFinalAssistant ? segment[lastAssistantIndex]?.text ?? null : null
    const executionMessages = canUseFinalAssistant ? segment.filter((_, index) => index !== lastAssistantIndex) : segment
    const hasTaskSignals = classifyConversationKind({
      todoCount: turnTodoList.length,
      toolOutputCount: segment.filter((message) => historyMessageSemantic(message) === 'tool_output').length,
      handoffCount: segment.filter((message) => historyMessageSemantic(message) === 'handoff').length,
      internalCount: segment.filter((message) => historyMessageSemantic(message) === 'system').length,
    }) === 'agent_task'
    // The history payload has no terminal status/reason. Keep the replay neutral
    // even when every persisted Todo is done instead of inventing a completed run.
    const completed = false
    return normalizeConversationTurn({
      id: `history-turn-${start}`,
      userText: messages[start]?.text ?? '',
      phase: completed ? 'completed' : 'idle',
      hasTaskSignals,
      execution: historicalExecution(executionMessages, turnTodoList, completed),
      assistantText: finalAnswer,
    })
  })
}

export function executionToPresentation(state: ExecutionState): ExecutionPresentation {
  const toolGroups = groupTools(state.tools.map((tool) => ({ name: tool.name, text: tool.result ?? JSON.stringify(tool.args ?? {}) })))
  const details: DetailedExecutionEntry[] = [
    ...state.narrativeUpdates.map((item) => ({ id: item.id, kind: 'narrative' as const, text: item.text })),
    ...state.timeline.filter((item) => item.kind === 'handoff' || item.kind === 'error').map((item) => ({ id: item.id, kind: 'system' as const, text: item.detail ? `${item.title}：${item.detail}` : item.title })),
  ]
  return {
    source: 'live', status: state.status, phase: state.phase, activeAgent: state.activeAgent, currentActivity: state.currentActivity,
    keyProgress: unique([...state.completedSteps, ...state.keyFindings, ...state.keyProgress]), narrativeUpdates: state.narrativeUpdates, details, toolGroups,
    completedTasks: state.tasks.filter((task) => task.done).length, totalTasks: state.tasks.length, evidenceCount: state.evidence.length,
    totalSteps: state.totalSteps || state.timeline.length,
    agentCount: new Set(state.timeline.map((item) => item.agent).filter(Boolean)).size || (state.timeline.length ? 1 : 0),
    error: state.error, expanded: state.executionExpanded,
    elapsedMs: state.startedAt && state.endedAt ? Math.max(0, state.endedAt - state.startedAt) : null,
    startedAt: state.startedAt, endedAt: state.endedAt,
  }
}

export function liveExecutionToTurn(question: string, state: ExecutionState): ConversationTurn {
  const task = hasAgentTaskSignals(state)
  const directText = state.assistantReply || state.finalAnswer || state.report
  const taskText = state.phase === 'awaiting_user'
    ? state.assistantReply
    : state.phase === 'reporting'
      ? state.finalAnswer || state.assistantReply || state.report
      : state.phase === 'completed' || state.phase === 'stopped' || state.phase === 'error'
        ? state.finalAnswer
        : ''
  return normalizeConversationTurn({
    id: 'live-turn', userText: question, phase: state.phase, hasTaskSignals: task, execution: executionToPresentation(state),
    assistantText: task ? taskText : directText,
    isFinalStreaming: Boolean((!task && state.status === 'running' && directText) || (task && state.phase === 'reporting' && taskText)),
  })
}

export function commitVisibleLiveTurn(turns: ConversationTurn[], question: string, state: ExecutionState): ConversationTurn[] {
  if (!question.trim()) return turns
  const turn = liveExecutionToTurn(question, state)
  if (!turn.finalAnswer && !turn.execution) return turns
  return [...turns, { ...turn, id: `committed-live-turn-${turns.length + 1}`, isFinalStreaming: false }]
}
