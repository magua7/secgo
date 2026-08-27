import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { KeysStatus, VisionStatus } from '../../types/api'
import { SettingsPanel } from './SettingsPanel'

const apiMocks = vi.hoisted(() => ({
  getKeysStatus: vi.fn(),
  buildSetupPayload: vi.fn(() => ({ default: {}, agents: {}, validate_keys: true })),
  saveSetup: vi.fn(),
  saveVisionConfig: vi.fn(),
  testVisionConfig: vi.fn(),
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

const visionStatus = (overrides: Partial<VisionStatus> = {}): VisionStatus => ({
  enabled: false,
  mode: 'reuse',
  configured: false,
  subscription: '',
  model_id: '',
  provider: 'openai',
  base_url: '',
  has_api_key: false,
  status: 'unconfigured',
  test_message: '',
  tested_at: null,
  ...overrides,
})

beforeEach(() => {
  apiMocks.getKeysStatus.mockReset().mockResolvedValue(status())
  apiMocks.saveSetup.mockReset().mockResolvedValue({
    ok: true,
    saved: true,
    next: '/',
    validation: { default: { ok: true, error: null } },
  })
  apiMocks.saveVisionConfig.mockReset().mockResolvedValue({ ok: true, saved: true })
  apiMocks.testVisionConfig.mockReset().mockResolvedValue({ ok: true, status: 'verified' })
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

describe('SettingsPanel vision settings', () => {
  const codingSub = { name: 'coding', provider: 'openai', model: 'deepseek-chat', base_url: 'https://coding.example/v1', has_key: true }
  const withVision = (vision: VisionStatus, subscriptions = [codingSub]): KeysStatus => ({
    ...status(),
    subscriptions,
    vision,
  })

  it('uses a dropdown (select) for the vision subscription', async () => {
    apiMocks.getKeysStatus.mockResolvedValue(withVision(
      visionStatus({ enabled: true, mode: 'reuse', subscription: 'coding', model_id: 'gpt-4o', status: 'pending', configured: true }),
      [
        codingSub,
        { name: 'vision-openai', provider: 'openai', model: 'gpt-4o', base_url: 'https://v.example/v1', has_key: true },
      ],
    ))
    render(<SettingsPanel onClose={vi.fn()} />)

    const select = await screen.findByRole('combobox', { name: '模型订阅' })
    expect(select.tagName).toBe('SELECT')
    expect(select).toHaveValue('coding')
    expect(screen.getByRole('option', { name: /vision-openai · openai · gpt-4o/ })).toBeInTheDocument()
  })

  it('blocks save when enabled but incomplete and prompts to select subscription and model', async () => {
    const user = userEvent.setup()
    apiMocks.getKeysStatus.mockResolvedValue(withVision(
      visionStatus({ enabled: true, mode: 'reuse', subscription: 'coding', model_id: '', status: 'unconfigured' }),
    ))
    render(<SettingsPanel onClose={vi.fn()} />)

    await user.click(await screen.findByRole('button', { name: '保存配置' }))
    expect(await screen.findByText('请选择模型订阅并填写视觉模型')).toBeInTheDocument()
    expect(apiMocks.saveVisionConfig).not.toHaveBeenCalled()
  })

  it('shows the verified capability status', async () => {
    apiMocks.getKeysStatus.mockResolvedValue(withVision(
      visionStatus({ enabled: true, mode: 'reuse', subscription: 'coding', model_id: 'gpt-4o', status: 'verified', configured: true }),
    ))
    render(<SettingsPanel onClose={vi.fn()} />)
    expect(await screen.findByText('● 可用')).toBeInTheDocument()
  })

  it('shows the failed capability status with its message', async () => {
    apiMocks.getKeysStatus.mockResolvedValue(withVision(
      visionStatus({ enabled: true, mode: 'reuse', subscription: 'coding', model_id: 'deepseek-chat', status: 'failed', test_message: '当前模型不接受图片输入' }),
    ))
    render(<SettingsPanel onClose={vi.fn()} />)
    expect(await screen.findByText('● 不可用')).toBeInTheDocument()
    expect(screen.getByText('上次检测失败：当前模型不接受图片输入')).toBeInTheDocument()
  })

  it('runs a capability test and refreshes status', async () => {
    const user = userEvent.setup()
    apiMocks.getKeysStatus.mockResolvedValueOnce(withVision(
      visionStatus({ enabled: true, mode: 'reuse', subscription: 'coding', model_id: 'gpt-4o', status: 'pending', configured: true }),
    )).mockResolvedValueOnce(withVision(
      visionStatus({ enabled: true, mode: 'reuse', subscription: 'coding', model_id: 'gpt-4o', status: 'verified', configured: true }),
    ))
    render(<SettingsPanel onClose={vi.fn()} />)

    await user.click(await screen.findByRole('button', { name: '测试视觉能力' }))
    await waitFor(() => expect(apiMocks.testVisionConfig).toHaveBeenCalledTimes(1))
    expect(await screen.findByText('视觉能力验证通过')).toBeInTheDocument()
    expect(await screen.findByText('● 可用')).toBeInTheDocument()
  })

  it('switches to custom mode and shows provider/baseURL/modelId/apiKey', async () => {
    const user = userEvent.setup()
    apiMocks.getKeysStatus.mockResolvedValue(withVision(
      visionStatus({ enabled: true, mode: 'reuse', subscription: 'coding', model_id: 'gpt-4o', status: 'pending', configured: true }),
    ))
    render(<SettingsPanel onClose={vi.fn()} />)

    await user.click(await screen.findByRole('radio', { name: '自定义模型' }))
    expect(screen.getByLabelText('Vision Provider')).toBeInTheDocument()
    expect(screen.getByLabelText('Vision Base URL')).toBeInTheDocument()
    expect(screen.getByLabelText('Vision Model ID')).toBeInTheDocument()
    expect(screen.getByLabelText('Vision API Key')).toBeInTheDocument()
    expect(screen.queryByLabelText('模型订阅')).not.toBeInTheDocument()
  })

  it('does not show baseURL or API key fields in reuse mode', async () => {
    apiMocks.getKeysStatus.mockResolvedValue(withVision(
      visionStatus({ enabled: true, mode: 'reuse', subscription: 'coding', model_id: 'gpt-4o', status: 'pending', configured: true }),
    ))
    render(<SettingsPanel onClose={vi.fn()} />)
    await screen.findByRole('combobox', { name: '模型订阅' })
    expect(screen.queryByLabelText('Vision Base URL')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Vision API Key')).not.toBeInTheDocument()
  })

  it('blocks custom save without an API key on first configuration', async () => {
    const user = userEvent.setup()
    apiMocks.getKeysStatus.mockResolvedValue(withVision(
      visionStatus({ enabled: true, mode: 'custom', model_id: 'qwen-vl-max', provider: 'openai', base_url: 'https://v.example/v1', has_api_key: false, status: 'unconfigured' }),
    ))
    render(<SettingsPanel onClose={vi.fn()} />)

    await user.click(await screen.findByRole('button', { name: '保存配置' }))
    expect(await screen.findByText('请填写 API Key')).toBeInTheDocument()
    expect(apiMocks.saveVisionConfig).not.toHaveBeenCalled()
  })

  it('sends provider/baseURL/modelId/apiKey when saving a custom config', async () => {
    const user = userEvent.setup()
    apiMocks.getKeysStatus.mockResolvedValue(withVision(
      visionStatus({ enabled: true, mode: 'custom', model_id: 'qwen-vl-max', provider: 'openai', base_url: 'https://v.example/v1', has_api_key: false, status: 'unconfigured' }),
    ))
    render(<SettingsPanel onClose={vi.fn()} />)

    await user.type(await screen.findByLabelText('Vision API Key'), 'custom-secret')
    await user.click(screen.getByRole('button', { name: '保存配置' }))

    await waitFor(() => expect(apiMocks.saveVisionConfig).toHaveBeenCalledTimes(1))
    expect(apiMocks.saveVisionConfig).toHaveBeenCalledWith(expect.objectContaining({
      mode: 'custom', provider: 'openai', baseURL: 'https://v.example/v1', modelId: 'qwen-vl-max', apiKey: 'custom-secret',
    }))
  })
})
