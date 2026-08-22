import type { ExecutionState } from '../../types/execution'
import type { ExecutionTraceViewModel } from '../../types/executionTrace'
import type { HistoryMessage, TodoItem } from '../../types/session'
import { historyMessagesToTurns, historyMessageSemantic, hasAgentTaskSignals } from '../conversation/conversationAdapter'
import { describeHistoricalToolOutput, normalizeHistoryTraceText } from './historyTraceText'

export function liveExecutionToTrace(state: ExecutionState): ExecutionTraceViewModel {
  const task = hasAgentTaskSignals(state)
  return {
    mode: 'live',
    kind: task ? 'agent_task' : 'direct_response',
    status: state.status,
    activeAgent: state.activeAgent,
    timeline: task ? state.timeline : [],
    evidence: task ? state.evidence : [],
    resources: task ? state.tools : [],
    notice: null,
  }
}

export function historyMessagesToTrace(messages: HistoryMessage[], todoList: TodoItem[], turnId?: string): ExecutionTraceViewModel {
  const starts = messages.reduce<number[]>((items, message, index) => {
    if (historyMessageSemantic(message) === 'user') items.push(index)
    return items
  }, [])
  const requestedStart = turnId?.match(/^history-turn-(\d+)$/)?.[1]
  const parsedStart = requestedStart === undefined ? undefined : Number(requestedStart)
  const selectedStart = parsedStart !== undefined && starts.includes(parsedStart) ? parsedStart : starts.at(-1)
  const selectedPosition = selectedStart === undefined ? -1 : starts.indexOf(selectedStart)
  const selectedEnd = selectedPosition >= 0 ? starts[selectedPosition + 1] ?? messages.length : messages.length
  const scopedMessages = selectedStart === undefined ? messages : messages.slice(selectedStart, selectedEnd)
  const scopedTodoList = selectedPosition === starts.length - 1 ? todoList : []
  const turns = historyMessagesToTurns(scopedMessages, scopedTodoList)
  const task = turns.some((turn) => turn.kind === 'agent_task')
  const timeline: ExecutionTraceViewModel['timeline'] = []
  if (task) scopedMessages.forEach((message, index) => {
    const semantic = historyMessageSemantic(message)
    if (semantic === 'tool_output') {
      const output = describeHistoricalToolOutput(message.text)
      timeline.push({ id: `history-trace-${index}`, at: null, kind: 'tool', title: output.title, detail: output.detail })
    } else if (semantic === 'handoff') timeline.push({ id: `history-trace-${index}`, at: null, kind: 'handoff', title: '已保存的内部交接文本', detail: normalizeHistoryTraceText(message.text) })
    else if (semantic === 'system') timeline.push({ id: `history-trace-${index}`, at: null, kind: 'status', title: '已保存的系统运行提示', detail: normalizeHistoryTraceText(message.text) })
    else if (semantic === 'assistant') timeline.push({ id: `history-trace-${index}`, at: null, kind: 'agent', title: '已保存的 Agent 文本', detail: normalizeHistoryTraceText(message.text) })
  })
  return {
    mode: 'history-readonly',
    kind: scopedMessages.length === 0 ? 'empty' : task ? 'agent_task' : 'direct_response',
    status: 'idle',
    activeAgent: 'agent',
    timeline,
    evidence: [],
    resources: [],
    notice: task ? '部分历史执行细节未保存，仅展示可恢复记录。' : null,
  }
}
