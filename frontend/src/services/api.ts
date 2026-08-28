import type { AgentId, AgentOverrideInputs, ChatResponse, KeysStatus, LoginResponse, ModelConfigInput, SessionsResponse, SetupPayload, SetupResponse, VisionConfigInput, VisionConfigResponse, VisionTestRequest, VisionTestResponse } from '../types/api'
import type { SessionConversationResponse } from '../types/session'

export class ApiError extends Error {
  constructor(message: string, public readonly status: number, public readonly redirectTo: string | null = null, public readonly body: unknown = null) {
    super(message)
    this.name = 'ApiError'
  }
}

export async function apiRequest<T>(url: string, options: RequestInit = {}): Promise<T> {
  const response = await window.fetch(url, { credentials: 'same-origin', ...options })
  if (!response.ok) {
    let message = `请求失败（${response.status}）`
    let responseBody: unknown = null
    try {
      responseBody = await response.json()
      const body = responseBody as { error?: string; detail?: string; message?: string }
      message = body.error ?? body.detail ?? body.message ?? message
    } catch { /* non-JSON response */ }
    throw new ApiError(message, response.status, response.status === 401 ? '/login' : null, responseBody)
  }
  return response.json() as Promise<T>
}

export async function login(password: string): Promise<LoginResponse> {
  const body = new FormData()
  body.append('password', password)
  return apiRequest<LoginResponse>('/api/login', { method: 'POST', body })
}

export const logout = (): Promise<{ ok: boolean }> => apiRequest('/api/logout', { method: 'POST' })
export const getKeysStatus = (): Promise<KeysStatus> => apiRequest('/api/keys-status')
export const getSessions = (): Promise<SessionsResponse> => apiRequest('/api/sessions')
export const getSessionMessages = (id: string): Promise<SessionConversationResponse> => apiRequest(`/api/sessions/${encodeURIComponent(id)}/messages`)

export interface McpServerStatus { name: string; connected: boolean; tool_count: number }
export interface McpStatus {
  running: boolean; connected: boolean; server_count: number; servers: McpServerStatus[]; tool_count: number; tools: string[]; configured: boolean
}
export const getMcpStatus = (): Promise<McpStatus> => apiRequest('/api/mcp-status')
export const cancelSession = (id: string): Promise<{ sessionId: string; cancelled: boolean }> => apiRequest(`/api/sessions/${encodeURIComponent(id)}/cancel`, { method: 'POST' })
export const deleteSession = (id: string): Promise<{ sessionId: string; deleted: boolean }> => apiRequest(`/api/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' })
export const renameSession = (id: string, title: string): Promise<{ sessionId: string; title: string }> => apiRequest(`/api/sessions/${encodeURIComponent(id)}/title`, {
  method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }),
})

export interface UploadedAttachment {
  id: string
  name: string
  mimeType: string
  kind: string
  size: number
  sha256: string
}

const arrayBufferToBase64 = (buffer: ArrayBuffer): string => {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  const chunkSize = 0x8000
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize))
  }
  return window.btoa(binary)
}

const readFileAsArrayBuffer = (file: File): Promise<ArrayBuffer> => new Promise((resolve, reject) => {
  const reader = new FileReader()
  reader.onload = () => reader.result instanceof ArrayBuffer ? resolve(reader.result) : reject(new Error('无法读取附件'))
  reader.onerror = () => reject(reader.error ?? new Error('无法读取附件'))
  reader.readAsArrayBuffer(file)
})

export async function uploadAttachment(file: File): Promise<UploadedAttachment> {
  const data = arrayBufferToBase64(await readFileAsArrayBuffer(file))
  const result = await apiRequest<{ ok: boolean; attachment: UploadedAttachment }>('/api/attachments', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: file.name, mimeType: file.type || 'application/octet-stream', data }),
  })
  return result.attachment
}

// 已上传附件（仅图片）内容地址：用户消息缩略图 / 点击放大预览使用
export const attachmentImageUrl = (sessionId: string | null | undefined, attachmentId: string): string =>
  `/api/sessions/${encodeURIComponent(sessionId ?? '')}/attachments/${encodeURIComponent(attachmentId)}/content`

export const sendChat = (message: string, sessionId?: string, attachmentIds?: string[]): Promise<ChatResponse> => apiRequest('/api/chat', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message, sessionId, attachments: attachmentIds ?? [] }),
})

const AGENT_IDS: AgentId[] = ['planner', 'research', 'builder', 'operator']

const emptyAgentInputs = (): AgentOverrideInputs => ({
  planner: { enabled: false, config: { provider: '', base_url: '', model: '', api_key: '' } },
  research: { enabled: false, config: { provider: '', base_url: '', model: '', api_key: '' } },
  builder: { enabled: false, config: { provider: '', base_url: '', model: '', api_key: '' } },
  operator: { enabled: false, config: { provider: '', base_url: '', model: '', api_key: '' } },
})

const isAgentInputs = (value: AgentOverrideInputs | ModelConfigInput | null): value is AgentOverrideInputs =>
  Boolean(value && 'planner' in value && typeof value.planner === 'object' && 'enabled' in value.planner)

export function buildSetupPayload(defaultConfig: ModelConfigInput, agentValues: AgentOverrideInputs | ModelConfigInput | null, validateKeys: boolean): SetupPayload {
  const clean = (config: ModelConfigInput): ModelConfigInput => {
    const result: ModelConfigInput = { provider: config.provider.trim() || 'openai', base_url: config.base_url.trim(), model: config.model.trim() }
    if (config.api_key?.trim()) result.api_key = config.api_key.trim()
    return result
  }
  const source = isAgentInputs(agentValues) ? agentValues : emptyAgentInputs()
  if (agentValues && !isAgentInputs(agentValues)) source.planner = { enabled: true, config: agentValues }
  const agents = Object.fromEntries(AGENT_IDS.map((agentId) => [
    agentId,
    { enabled: source[agentId].enabled, config: clean(source[agentId].config) },
  ])) as AgentOverrideInputs
  return { default: clean(defaultConfig), agents, validate_keys: validateKeys }
}

export const saveSetup = (payload: SetupPayload): Promise<SetupResponse> => apiRequest('/api/setup-keys', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
})

export const saveVisionConfig = (payload: VisionConfigInput): Promise<VisionConfigResponse> => apiRequest('/api/vision-config', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
})

export const testVisionConfig = (payload?: VisionTestRequest): Promise<VisionTestResponse> => apiRequest('/api/vision-test', {
  method: 'POST',
  headers: payload ? { 'Content-Type': 'application/json' } : undefined,
  body: payload ? JSON.stringify(payload) : undefined,
})

export const resolvePostLoginDestination = (_ready: boolean): '/' => '/'

export function validateSetupForSave(defaultConfig: ModelConfigInput, agentValues: AgentOverrideInputs | ModelConfigInput | null, status?: KeysStatus | null): string | null {
  if (!defaultConfig.base_url.trim() || !defaultConfig.model.trim()) return '请完整填写默认模型配置'
  if (!defaultConfig.api_key?.trim() && !status?.default?.has_key) return '首次配置默认模型时必须输入 API Key'
  const agents = isAgentInputs(agentValues) ? agentValues : emptyAgentInputs()
  if (agentValues && !isAgentInputs(agentValues)) agents.planner = { enabled: true, config: agentValues }
  for (const agentId of AGENT_IDS) {
    const entry = agents[agentId]
    if (!entry.enabled) continue
    const label = agentId.charAt(0).toUpperCase() + agentId.slice(1)
    if (!entry.config.base_url.trim() || !entry.config.model.trim()) return `请完整填写 ${label} 专用模型配置`
    if (!entry.config.api_key?.trim() && !status?.agents?.[agentId]?.has_key) return `首次启用 ${label} 专用模型时必须输入 API Key`
  }
  return null
}

export function handleApiError(error: unknown): string {
  if (error instanceof ApiError && error.redirectTo) window.location.assign(error.redirectTo)
  return error instanceof Error ? error.message : '发生未知错误'
}