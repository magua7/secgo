import type { AgentId, NarrativeUpdate } from './execution'
import type { TodoItem } from './session'

// 后端 RunSnapshot 的状态/阶段词汇（与前端 ExecutionStatus/ConversationPhase 通过 adapter 映射）
export type SnapshotStatus = 'idle' | 'queued' | 'running' | 'awaiting_user' | 'completed' | 'stopped' | 'error'
export type SnapshotPhase = 'idle' | 'planning' | 'executing' | 'awaiting_user' | 'reporting' | 'completed' | 'stopped' | 'error'

export interface EvidenceRecord {
  id: string
  type: 'http' | 'file' | 'finding' | 'network' | 'artifact' | string
  title: string
  summary: string
  source: string
  timestamp?: number
  metadata?: Record<string, unknown>
}

export interface ResourceRecord {
  name: string
  args?: Record<string, unknown> | null
  result?: string | null
  status: 'running' | 'completed' | 'error'
  at?: number
}

export interface SnapshotTimelineItem {
  id: string
  at: number
  kind: 'status' | 'agent' | 'handoff' | 'tool' | 'finding' | 'error'
  agent?: AgentId
  title: string
  detail?: string
  status?: 'running' | 'completed' | 'error'
}

export interface RunSnapshot {
  run_id: string
  session_id: string
  turn_id: string
  status: SnapshotStatus
  phase: SnapshotPhase
  reason: string
  error: string | null
  active_agent: AgentId
  started_at: number | null
  ended_at: number | null
  current_activity: string
  narrative_updates: NarrativeUpdate[]
  key_progress: string[]
  key_findings: string[]
  tasks: TodoItem[]
  timeline: SnapshotTimelineItem[]
  evidence: EvidenceRecord[]
  resources: ResourceRecord[]
  final_report: string | null
  partial_report: string | null
  last_assistant_output?: string | null
  decisions?: Record<string, unknown>[]
  tool_count: number
  evidence_count: number
  total_steps: number
}