import type { SessionSummary } from './session'

export interface LoginResponse { ok: boolean; next?: string; error?: string }

export interface ModelConfig {
  provider: string
  base_url: string
  model: string
  api_key_masked?: string
}

export interface KeysStatus {
  auth_enabled: boolean
  ready: boolean
  has_default: boolean
  default: ModelConfig | null
  has_planner: boolean
  planner: ModelConfig | null
}

export interface ModelConfigInput {
  provider: string
  base_url: string
  model: string
  api_key?: string
}

export interface SetupPayload {
  default: ModelConfigInput
  planner: ModelConfigInput | null
  validate_keys: boolean
}

export interface SessionsResponse {
  sessions: SessionSummary[]
}

export interface ChatResponse {
  sessionId: string
  accepted: boolean
  resumed: boolean
}
