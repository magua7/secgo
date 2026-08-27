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

// 可选图片视觉（Vision）预处理模型状态（复用 subscriptions 体系，非新 Agent）
export type VisionCapabilityStatus = 'unconfigured' | 'pending' | 'verified' | 'failed'
export type VisionMode = 'reuse' | 'custom'

export interface VisionStatus {
  enabled: boolean
  mode: VisionMode
  configured: boolean
  subscription: string
  model_id: string
  provider: string
  base_url: string
  has_api_key: boolean
  status: VisionCapabilityStatus
  test_message: string
  tested_at?: number | null
}

// 已有订阅（供 Vision 设置页下拉选择；不含 API Key）
export interface SubscriptionOption {
  name: string
  provider: string
  model: string
  base_url: string
  has_key: boolean
}

export interface KeysStatus {
  auth_enabled: boolean
  ready: boolean
  has_default?: boolean
  default: ModelKeyStatus | null
  agents: Record<AgentId, ModelKeyStatus | null>
  vision?: VisionStatus | null
  subscriptions?: SubscriptionOption[]
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

export interface VisionConfigInput {
  enabled: boolean
  mode: VisionMode
  subscription: string
  modelId: string
  provider: string
  baseURL: string
  apiKey?: string
}

export interface VisionConfigResponse {
  ok: boolean
  saved: boolean
  error?: string
}

export interface VisionTestRequest {
  mode: VisionMode
  subscription: string
  modelId: string
  provider: string
  baseURL: string
  apiKey: string
}

export interface VisionTestResponse {
  ok: boolean
  status: VisionCapabilityStatus
  message?: string
  error?: string
  temporary?: boolean
}

export interface SessionsResponse {
  sessions: SessionSummary[]
}

export interface ChatResponse {
  sessionId: string
  turnId?: string
  accepted: boolean
  resumed: boolean
}
