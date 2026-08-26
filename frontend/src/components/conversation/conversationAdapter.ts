import type { ConversationTurn, DetailedExecutionEntry, ExecutionPresentation, ToolExecutionGroup } from '../../types/conversation'
import type { ConversationPhase, ExecutionState, ExecutionStatus } from '../../types/execution'
import type { PersistedTurn } from '../../types/session'
import type { RunSnapshot } from '../../types/snapshot'
import type { MessageAttachment } from '../../types/attachment'

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
  attachments?: MessageAttachment[]
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
    userMessage: { text: input.userText, attachments: input.attachments },
    execution: kind === 'agent_task' ? input.execution : null,
    finalAnswer: input.assistantText?.trim() || null,
    isFinalStreaming: Boolean(input.isFinalStreaming),
  }
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

export function liveExecutionToTurn(question: string, state: ExecutionState, attachments?: MessageAttachment[]): ConversationTurn {
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
    id: 'live-turn', userText: question, attachments, phase: state.phase, hasTaskSignals: task, execution: executionToPresentation(state),
    assistantText: task ? taskText : directText,
    isFinalStreaming: Boolean((!task && state.status === 'running' && directText) || (task && state.phase === 'reporting' && taskText)),
  })
}

const snapshotStatusMap: Record<string, ExecutionStatus> = {
  idle: 'idle', queued: 'loading', running: 'running', awaiting_user: 'awaiting_input',
  completed: 'completed', stopped: 'cancelled', error: 'error',
}
const snapshotPhaseMap: Record<string, ConversationPhase> = {
  idle: 'idle', planning: 'planning', executing: 'executing', awaiting_user: 'awaiting_user',
  reporting: 'reporting', completed: 'completed', stopped: 'stopped', error: 'error',
}

// 历史 RunSnapshot → ExecutionState：让历史进入与实时完全相同的 ExecutionViewModel 数据流。
export function snapshotToExecutionState(snapshot: RunSnapshot): ExecutionState {
  const report = snapshot.final_report ?? snapshot.partial_report ?? snapshot.last_assistant_output ?? ''
  const status = snapshotStatusMap[snapshot.status] ?? 'idle'
  const phase = snapshotPhaseMap[snapshot.phase] ?? 'idle'
  return {
    status,
    phase,
    activeAgent: snapshot.active_agent ?? 'planner',
    tasks: snapshot.tasks ?? [],
    timeline: (snapshot.timeline ?? []).map((item) => ({ ...item })),
    tools: (snapshot.resources ?? []).map((resource) => ({
      name: resource.name,
      args: resource.args ?? undefined,
      result: resource.result ?? undefined,
      status: resource.status,
    })),
    evidence: (snapshot.evidence ?? []).map((item) => ({
      id: item.id, type: item.type, title: item.title, source: item.source,
      summary: item.summary, timestamp: item.timestamp, metadata: item.metadata,
    })),
    findings: snapshot.key_findings ?? [],
    completedSteps: (snapshot.tasks ?? []).filter((task) => task.done).map((task) => task.text),
    keyFindings: snapshot.key_findings ?? [],
    narrativeUpdates: snapshot.narrative_updates ?? [],
    keyProgress: snapshot.key_progress ?? [],
    report,
    currentActivity: snapshot.current_activity ?? '',
    assistantReply: report,
    finalAnswer: report,
    lastAssistantOutput: snapshot.last_assistant_output ?? '',
    lastStreamAgent: null,
    startedAt: snapshot.started_at ?? null,
    endedAt: snapshot.ended_at ?? null,
    totalSteps: snapshot.total_steps ?? 0,
    reason: snapshot.reason ?? '',
    error: snapshot.error ?? null,
    executionExpanded: status !== 'completed',
    connection: 'idle',
  }
}

// 持久化 Turn → ConversationTurn（复用统一 Renderer；普通 direct_response 也是正式 Turn）。
export function persistedTurnToConversationTurn(turn: PersistedTurn): ConversationTurn {
  const userText = turn.userMessage?.text ?? ''
  const attachments = turn.userMessage?.attachments
  if (!turn.execution) {
    return {
      id: turn.id,
      kind: 'direct_response',
      phase: 'idle',
      userMessage: { text: userText, attachments },
      execution: null,
      finalAnswer: turn.assistantAnswer?.trim() || null,
      isFinalStreaming: false,
    }
  }
  const state = snapshotToExecutionState(turn.execution)
  const hasTaskSignals = hasAgentTaskSignals(state)
  return normalizeConversationTurn({
    id: turn.id,
    userText,
    attachments,
    phase: state.phase,
    hasTaskSignals,
    execution: executionToPresentation(state),
    assistantText: turn.assistantAnswer ?? state.finalAnswer,
    isFinalStreaming: false,
  })
}

export function persistedTurnsToConversationTurns(turns: PersistedTurn[]): ConversationTurn[] {
  return turns.map(persistedTurnToConversationTurn)
}
