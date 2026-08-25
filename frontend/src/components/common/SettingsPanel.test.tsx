import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { KeysStatus } from '../../types/api'
import { SettingsPanel } from './SettingsPanel'

const apiMocks = vi.hoisted(() => ({
  getKeysStatus: vi.fn(),
  buildSetupPayload: vi.fn(() => ({ default: {}, agents: {}, validate_keys: true })),
  saveSetup: vi.fn(),
  validateSetupForSave: vi.fn(() => null),
  handleApiError: vi.fn((error: unknown) => error instanceof Error ? error.message : '错误'),
  logout: vi.fn(),
}))

vi.mock('../../services/api', () => apiMocks)

const config = (name: string, enabled: boolean, masked: string) => ({
  enabled,
  provider: 'openai',
  base_url: `https://${name}.example/v1`,
  model: `${name}-model`,
  has_key: Boolean(masked),
  api_key_masked: masked,
})

const status = (overrides: Partial<KeysStatus['agents']> = {}, defaultMask = 'def***old'): KeysStatus => ({
  auth_enabled: true,
  ready: true,
  default: config('default', true, defaultMask),
  agents: {
    planner: null,
    research: null,
    builder: null,
    operator: null,
    ...overrides,
  },
})

beforeEach(() => {
  apiMocks.getKeysStatus.mockReset().mockResolvedValue(status())
  apiMocks.saveSetup.mockReset().mockResolvedValue({
    ok: true,
    saved: true,
    next: '/',
    validation: { default: { ok: true, error: null } },
  })
  apiMocks.buildSetupPayload.mockClear()
  apiMocks.validateSetupForSave.mockReset().mockReturnValue(null)
})

afterEach(cleanup)

describe('SettingsPanel model settings', () => {
  it('renders config-driven switches for all four Agents', async () => {
    render(<SettingsPanel onClose={vi.fn()} />)

    expect(await screen.findByText('高级：Agent 专用模型（可选）')).toBeInTheDocument()
    for (const name of ['Planner', 'Research', 'Builder', 'Operator']) {
      expect(screen.getByRole('switch', { name: `${name} 使用独立模型` })).toBeInTheDocument()
    }
    expect(screen.getAllByText('复用默认模型')).toHaveLength(4)
  })

  it('only changes an Agent override from its Switch', async () => {
    const user = userEvent.setup()
    render(<SettingsPanel onClose={vi.fn()} />)
    const toggle = await screen.findByRole('switch', { name: 'Research 使用独立模型' })

    await user.click(screen.getByText('Research'))
    expect(toggle).toHaveAttribute('aria-checked', 'false')
    expect(screen.queryByLabelText('Research 专用模型 API Key')).not.toBeInTheDocument()

    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByLabelText('Research 专用模型 API Key')).toBeInTheDocument()
  })

  it('refreshes backend masks and clears plaintext after a successful replacement', async () => {
    const user = userEvent.setup()
    apiMocks.getKeysStatus
      .mockResolvedValueOnce(status())
      .mockResolvedValueOnce(status({}, 'def***new'))
    render(<SettingsPanel onClose={vi.fn()} />)
    const input = await screen.findByLabelText('默认模型（必填） API Key')

    await user.type(input, 'new-default-secret')
    await user.click(screen.getByRole('button', { name: '保存设置' }))

    await waitFor(() => expect(apiMocks.getKeysStatus).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('✓ 当前已配置 def***new')).toBeInTheDocument()
    expect(input).toHaveValue('')
    expect(screen.getByText('模型配置已保存')).toBeInTheDocument()
  })

  it('clears plaintext after save even when the status refresh fails', async () => {
    const user = userEvent.setup()
    apiMocks.getKeysStatus
      .mockResolvedValueOnce(status())
      .mockRejectedValueOnce(new Error('状态接口不可用'))
    render(<SettingsPanel onClose={vi.fn()} />)
    const input = await screen.findByLabelText('默认模型（必填） API Key')

    await user.type(input, 'new-default-secret')
    await user.click(screen.getByRole('button', { name: '保存设置' }))

    await waitFor(() => expect(apiMocks.getKeysStatus).toHaveBeenCalledTimes(2))
    expect(input).toHaveValue('')
    expect(screen.getByText(/模型配置已保存，但状态刷新失败/)).toBeInTheDocument()
  })

  it('keeps the old mask visible beside a failed replacement', async () => {
    const user = userEvent.setup()
    apiMocks.getKeysStatus.mockResolvedValue(status({
      research: config('research', true, 'res***old'),
    }))
    apiMocks.saveSetup.mockRejectedValueOnce(Object.assign(new Error('模型配置未保存，请检查 Research 配置'), {
      body: {
        ok: false,
        saved: false,
        validation: {
          default: { ok: true, error: null },
          research: { ok: false, error: 'Research 模型新 API Key 校验失败：HTTP 401' },
        },
      },
    }))
    render(<SettingsPanel onClose={vi.fn()} />)
    const input = await screen.findByLabelText('Research 专用模型 API Key')

    await user.type(input, 'bad-research-key')
    await user.click(screen.getByRole('button', { name: '保存设置' }))

    expect(await screen.findByText('✓ 当前已配置 res***old')).toBeInTheDocument()
    expect(screen.getByText('✕ Research 模型新 API Key 校验失败：HTTP 401')).toBeInTheDocument()
    expect(input).toHaveValue('bad-research-key')
    expect(apiMocks.getKeysStatus).toHaveBeenCalledTimes(1)
  })

  it('accepts a custom provider without resetting URL or model', async () => {
    const user = userEvent.setup()
    render(<SettingsPanel onClose={vi.fn()} />)
    const provider = await screen.findByRole('combobox', { name: '默认模型（必填） Provider' })

    await user.clear(provider)
    await user.type(provider, 'SiliconFlow')
    await user.tab()

    expect(provider).toHaveValue('SiliconFlow')
    expect(screen.getByDisplayValue('https://default.example/v1')).toBeInTheDocument()
    expect(screen.getByDisplayValue('default-model')).toBeInTheDocument()
  })
})
