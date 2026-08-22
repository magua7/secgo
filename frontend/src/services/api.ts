import type { ChatResponse, KeysStatus, LoginResponse, ModelConfigInput, SessionsResponse, SetupPayload } from '../types/api'
import type { SessionMessagesResponse } from '../types/session'

export class ApiError extends Error {
  constructor(message: string, public readonly status: number, public readonly redirectTo: string | null = null) {
    super(message)
    this.name = 'ApiError'
  }
}

export async function apiRequest<T>(url: string, options: RequestInit = {}): Promise<T> {
  const response = await window.fetch(url, { credentials: 'same-origin', ...options })
  if (!response.ok) {
    let message = `请求失败（${response.status}）`
    try {
      const body = await response.json() as { error?: string; detail?: string }
      message = body.error ?? body.detail ?? message
    } catch { /* non-JSON response */ }
    throw new ApiError(message, response.status, response.status === 401 ? '/login' : null)
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
export const getSessionMessages = (id: string): Promise<SessionMessagesResponse> => apiRequest(`/api/sessions/${encodeURIComponent(id)}/messages`)
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

export const sendChat = (message: string, sessionId?: string, attachmentIds?: string[]): Promise<ChatResponse> => apiRequest('/api/chat', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message, sessionId, attachments: attachmentIds ?? [] }),
})

export function buildSetupPayload(defaultConfig: ModelConfigInput, planner: ModelConfigInput | null, validateKeys: boolean): SetupPayload {
  const clean = (config: ModelConfigInput): ModelConfigInput => {
    const result: ModelConfigInput = { provider: config.provider.trim() || 'openai', base_url: config.base_url.trim(), model: config.model.trim() }
    if (config.api_key?.trim()) result.api_key = config.api_key.trim()
    return result
  }
  return { default: clean(defaultConfig), planner: planner ? clean(planner) : null, validate_keys: validateKeys }
}

export const saveSetup = (payload: SetupPayload): Promise<{ ok: boolean; next: string }> => apiRequest('/api/setup-keys', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
})

export const resolvePostLoginDestination = (_ready: boolean): '/' => '/'

export function validateSetupForSave(defaultConfig: ModelConfigInput, planner: ModelConfigInput | null): string | null {
  if (!defaultConfig.base_url.trim() || !defaultConfig.model.trim()) return '请完整填写默认模型配置'
  if (!defaultConfig.api_key?.trim()) return '保存配置时必须重新输入默认模型 API Key'
  if (planner && (!planner.base_url.trim() || !planner.model.trim() || !planner.api_key?.trim())) return '启用 Planner 专用模型时必须完整填写配置和 API Key'
  return null
}

export function handleApiError(error: unknown): string {
  if (error instanceof ApiError && error.redirectTo) window.location.assign(error.redirectTo)
  return error instanceof Error ? error.message : '发生未知错误'
}
