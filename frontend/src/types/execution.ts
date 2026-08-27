import type { TodoItem } from './session'

export type AgentId = 'planner' | 'research' | 'operator' | 'builder' | string
export type ExecutionStatus = 'idle' | 'loading' | 'running' | 'awaiting_input' | 'completed' | 'cancelled' | 'error'
export type ConversationPhase = 'idle' | 'direct_response' | 'planning' | 'executing' | 'awaiting_user' | 'reporting' | 'completed' | 'stopped' | 'error'

export interface TimelineItem {
  id: string
  at: number
  kind: 'status' | 'agent' | 'handoff' | 'tool' | 'finding' | 'error'
  agent?: AgentId
  title: string
  detail?: string
  status?: 'running' | 'completed' | 'error'
}

export interface ToolUse {
  name: string
  args?: Record<string, unknown>
  result?: string
  status: 'running' | 'completed' | 'error'
}

export interface DecisionRecord {
  id: string
  timestamp: number
  trigger: string
  trigger_detail: string
  observation: string
  candidates: { id: string; description: string; target_agent: string; suggested_tools: string[]; risk: string; expected_outcome: string }[]
  selected: string
  reason: string
  rejected: string[]
}

export interface EvidenceItem {
  id?: string
  type?: string
  title?: string
  source: string
  summary: string
  timestamp?: number
  metadata?: Record<string, unknown>
}

export interface NarrativeUpdate {
  id: string
  text: string
  agent: AgentId
  timestamp: number
}

export interface ExecutionState {
  status: ExecutionStatus
  phase: ConversationPhase
  activeAgent: AgentId
  tasks: TodoItem[]
  timeline: TimelineItem[]
  tools: ToolUse[]
  evidence: EvidenceItem[]
  decisions: DecisionRecord[]
  findings: string[]
  completedSteps: string[]
  keyFindings: string[]
  narrativeUpdates: NarrativeUpdate[]
  keyProgress: string[]
  report: string
  currentActivity: string
  assistantReply: string
  finalAnswer: string
  lastAssistantOutput: string
  lastStreamAgent: AgentId | null
  startedAt: number | null
  endedAt: number | null
  totalSteps: number
  reason: string
  error: string | null
  executionExpanded: boolean
  connection: 'idle' | 'connected' | 'reconnecting'
}