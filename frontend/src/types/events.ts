import type { AgentId, EvidenceItem } from './execution'
import type { TodoItem } from './session'

interface BaseData { session_id?: string; turn_id?: string; _event?: string }
export interface EngineStartData extends BaseData { user_input?: string }
export interface AgentThinkingData extends BaseData { agent_id?: AgentId }
export interface AgentSwitchData extends BaseData { from_agent_id?: AgentId; to_agent_id?: AgentId; reason?: string }
export interface ToolData extends BaseData { agent_id?: AgentId; tool_name?: string; args?: Record<string, unknown>; result?: unknown }
export interface StreamData extends BaseData { agent_id?: AgentId; chunk?: string; text?: string }
export interface EndData extends BaseData { reason?: string; total_steps?: number; error?: string; replan_count?: number; decision_count?: number }
export interface ErrorData extends BaseData { agent_id?: AgentId; error?: string }
export interface TodoData extends BaseData { todo_list?: TodoItem[] }
export interface AwaitingData extends BaseData { agent_id?: AgentId; message?: string }
export interface BudgetData extends BaseData { usage?: number; limit?: number }
export interface DecisionData extends BaseData { decision?: Record<string, unknown>; step?: number }
export interface EvidenceData extends BaseData { evidence?: EvidenceItem }
export interface PersistenceWarningData extends BaseData { error?: string }

export type ExecutionEvent =
  | { type: 'engine:start'; data: EngineStartData }
  | { type: 'agent:thinking'; data: AgentThinkingData }
  | { type: 'agent:switch'; data: AgentSwitchData }
  | { type: 'tool:call' | 'tool:stream-start' | 'tool:result' | 'tool:stream-end'; data: ToolData }
  | { type: 'llm:stream' | 'engine:text'; data: StreamData }
  | { type: 'todo:updated'; data: TodoData }
  | { type: 'engine:awaiting_input'; data: AwaitingData }
  | { type: 'engine:user_input'; data: BaseData & { input?: string } }
  | { type: 'engine:error'; data: ErrorData }
  | { type: 'budget:exceeded'; data: BudgetData }
  | { type: 'engine:evidence'; data: EvidenceData }
  | { type: 'decision:reason'; data: DecisionData }
  | { type: 'persistence:warning'; data: PersistenceWarningData }
  | { type: 'engine:end'; data: EndData }
  | { type: 'ui:reset'; data: BaseData }
  | { type: 'ui:toggle-execution'; data: BaseData }
  | { type: 'ui:connection'; data: BaseData & { connection: 'idle' | 'connected' | 'reconnecting' } }

export const SSE_EVENT_NAMES = [
  'engine:start', 'agent:thinking', 'agent:switch', 'tool:call', 'tool:result',
  'llm:stream', 'engine:text', 'engine:end', 'budget:exceeded', 'engine:error',
  'todo:updated', 'tool:stream-start', 'tool:stream-end', 'engine:awaiting_input',
  'engine:user_input', 'engine:evidence', 'persistence:warning', 'decision:reason',
] as const

export type SseEventName = typeof SSE_EVENT_NAMES[number]