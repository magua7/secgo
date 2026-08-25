import type { SessionSummary } from './session'

export interface LoginResponse { ok: boolean; next?: string; error?: string }

export interface ModelConfig {
  provider: string
  base_url: string
  model: string
  api_key_masked?: string
}

export type AgentId = 'planner' | 'research' | 'builder' | 'operator'
export type ConfigId = 'default' | AgentId

export interface ModelKeyStatus extends ModelConfig {
  enabled: boolean
  has_key: boolean
}

export interface KeysStatus {
  auth_enabled: boolean
  ready: boolean
  has_default?: boolean
  default: ModelKeyStatus | null
  agents: Record<AgentId, ModelKeyStatus | null>
  has_planner?: boolean
  planner?: ModelKeyStatus | null
}

export interface ModelConfigInput {
  provider: string
  base_url: string
  model: string
  api_key?: string
}

export interface AgentOverrideInput {
  enabled: boolean
  config: ModelConfigInput
}

export type AgentOverrideInputs = Record<AgentId, AgentOverrideInput>

export interface SetupPayload {
  default: ModelConfigInput
  agents: AgentOverrideInputs
  validate_keys: boolean
}

export interface ValidationResult {
  ok: boolean
  error: string | null
}

export interface SetupResponse {
  ok: boolean
  saved: boolean
  next?: string
  error?: string
  validation: Partial<Record<ConfigId, ValidationResult>>
}

export interface SessionsResponse {
  sessions: SessionSummary[]
}

export interface ChatResponse {
  sessionId: string
  accepted: boolean
  resumed: boolean
}
