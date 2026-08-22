import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, apiRequest, buildSetupPayload, resolvePostLoginDestination, sendChat, uploadAttachment, validateSetupForSave } from './api'

describe('api service', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('always sends same-origin credentials', async () => {
    const fetchMock = vi.spyOn(window, 'fetch').mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await apiRequest<{ ok: boolean }>('/api/test')
    expect(fetchMock).toHaveBeenCalledWith('/api/test', expect.objectContaining({ credentials: 'same-origin' }))
  })

  it('classifies auth and readiness failures', async () => {
    vi.spyOn(window, 'fetch').mockResolvedValueOnce(new Response('', { status: 401 })).mockResolvedValueOnce(new Response('', { status: 403 }))
    await expect(apiRequest('/api/test')).rejects.toEqual(expect.objectContaining({ redirectTo: '/login' }))
    await expect(apiRequest('/api/test')).rejects.toEqual(expect.objectContaining({ redirectTo: null }))
  })

  it('omits unchanged masked keys from setup payload', () => {
    const payload = buildSetupPayload({ provider: 'openai', base_url: 'https://api.test/v1', model: 'm', api_key: '' }, null, true)
    expect(payload.default).not.toHaveProperty('api_key')
    expect(payload.planner).toBeNull()
  })

  it('preserves an arbitrary OpenAI-compatible provider label', () => {
    const payload = buildSetupPayload({ provider: '  custom-proxy  ', base_url: 'https://proxy.test/v1', model: 'any-model', api_key: 'secret' }, null, true)
    expect(payload.default.provider).toBe('custom-proxy')
    expect(payload.default.base_url).toBe('https://proxy.test/v1')
    expect(payload.default.model).toBe('any-model')
  })

  it('always routes login to home', () => {
    expect(resolvePostLoginDestination(true)).toBe('/')
    expect(resolvePostLoginDestination(false)).toBe('/')
  })

  it('sends attachment ids with chat requests', async () => {
    const fetchMock = vi.spyOn(window, 'fetch').mockResolvedValue(new Response(JSON.stringify({ sessionId: 's', accepted: true, resumed: false }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await sendChat('分析附件', 'session-1', ['attachment-1'])
    expect(fetchMock).toHaveBeenCalledWith('/api/chat', expect.objectContaining({
      body: JSON.stringify({ message: '分析附件', sessionId: 'session-1', attachments: ['attachment-1'] }),
    }))
  })

  it('reads a File and uploads pure base64 data', async () => {
    const fetchMock = vi.spyOn(window, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      ok: true,
      attachment: { id: 'attachment-1', name: 'a.txt', mimeType: 'text/plain', kind: 'text', size: 2, sha256: 'hash' },
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    const uploaded = await uploadAttachment(new File(['hi'], 'a.txt', { type: 'text/plain' }))
    const request = fetchMock.mock.calls[0]?.[1]
    expect(JSON.parse(String(request?.body))).toEqual({ name: 'a.txt', mimeType: 'text/plain', data: 'aGk=' })
    expect(uploaded.id).toBe('attachment-1')
  })

  it('requires keys when saving because masked values are not returned to the browser', () => {
    expect(validateSetupForSave({ provider: 'openai', base_url: 'https://api.test/v1', model: 'm', api_key: '' }, null)).toContain('API Key')
    expect(validateSetupForSave({ provider: 'openai', base_url: 'https://api.test/v1', model: 'm', api_key: 'secret' }, null)).toBeNull()
  })
})
