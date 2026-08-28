import type { ConversationPhase, ExecutionStatus, NarrativeUpdate } from './execution'
import type { MessageAttachment } from './attachment'

export interface DetailedExecutionEntry {
  id: string
  kind: 'narrative' | 'tool' | 'system'
  text: string
}

export interface ToolExecutionGroup {
  name: string
  count: number
  entries: string[]
}

export interface ExecutionPresentation {
  source: 'live' | 'history'
  status: ExecutionStatus
  phase: ConversationPhase
  activeAgent: string
  currentActivity: string
  keyProgress: string[]
  narrativeUpdates: NarrativeUpdate[]
  details: DetailedExecutionEntry[]
  toolGroups: ToolExecutionGroup[]
  completedTasks: number
  totalTasks: number
  evidenceCount: number | null
  totalSteps: number
  agentCount: number
  error: string | null
  expanded: boolean
  elapsedMs: number | null
  startedAt: number | null
  endedAt: number | null
}

export interface ConversationTurn {
  id: string
  sessionId?: string
  kind: 'direct_response' | 'agent_task'
  phase: ConversationPhase
  userMessage: { text: string; attachments?: MessageAttachment[] }
  execution: ExecutionPresentation | null
  finalAnswer: string | null
  isFinalStreaming: boolean
}
