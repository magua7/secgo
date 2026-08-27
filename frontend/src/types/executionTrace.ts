import type { AgentId, DecisionRecord, EvidenceItem, ExecutionStatus, TimelineItem, ToolUse } from './execution'

export type ExecutionTraceTab = 'trace' | 'evidence' | 'decisions'

export interface ResourceGroup {
  name: string
  count: number
  type?: string
  invocations: ToolUse[]
}

export interface ExecutionTraceViewModel {
  mode: 'live' | 'history'
  kind: 'empty' | 'direct_response' | 'agent_task'
  status: ExecutionStatus
  activeAgent: AgentId
  timeline: Array<Omit<TimelineItem, 'at'> & { at: number | null }>
  evidence: EvidenceItem[]
  decisions: DecisionRecord[]
  resources: ResourceGroup[]
  notice: string | null
}
