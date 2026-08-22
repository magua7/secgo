import type { AgentId, EvidenceItem, ExecutionStatus, TimelineItem, ToolUse } from './execution'

export type ExecutionTraceTab = 'trace' | 'evidence' | 'resources'

export interface ExecutionTraceViewModel {
  mode: 'live' | 'history-readonly'
  kind: 'empty' | 'direct_response' | 'agent_task'
  status: ExecutionStatus
  activeAgent: AgentId
  timeline: Array<Omit<TimelineItem, 'at'> & { at: number | null }>
  evidence: EvidenceItem[]
  resources: ToolUse[]
  notice: string | null
}
