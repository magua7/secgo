import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SettingsPanel } from './SettingsPanel'

vi.mock('../../services/api', () => ({
  getKeysStatus: vi.fn().mockResolvedValue({
    ready: true,
    default: { provider: 'openai', base_url: 'https://gateway.example/v1', model: 'model-a', api_key_masked: 'sk-***123' },
    planner: null,
  }),
  buildSetupPayload: vi.fn(), saveSetup: vi.fn(), validateSetupForSave: vi.fn(),
  handleApiError: () => '错误', logout: vi.fn(),
}))

afterEach(cleanup)

describe('SettingsPanel', () => {
  it('combines default and Planner model controls under one primary section', async () => {
    render(<SettingsPanel onClose={vi.fn()} />)
    expect(screen.getByRole('button', { name: /模型配置/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Agent' })).not.toBeInTheDocument()
    expect(screen.getByText('默认模型（必填）')).toBeInTheDocument()
    expect(screen.getByText('高级：任务规划模型（可选）')).toBeInTheDocument()
    expect(screen.getByText('任务规划模型（Planner）')).toBeInTheDocument()
    expect(screen.queryByText(/所有配置均对应/)).not.toBeInTheDocument()
  })

  it('accepts a custom provider without resetting URL or model', async () => {
    const user = userEvent.setup()
    render(<SettingsPanel onClose={vi.fn()} />)
    const provider = await screen.findByRole('combobox', { name: '默认模型（必填） Provider' })

    await user.clear(provider)
    await user.type(provider, 'SiliconFlow')
    await user.tab()

    expect(provider).toHaveValue('SiliconFlow')
    expect(screen.getByDisplayValue('https://gateway.example/v1')).toBeInTheDocument()
    expect(screen.getByDisplayValue('model-a')).toBeInTheDocument()
  })

  it('only toggles Planner from the switch control', async () => {
    const user = userEvent.setup()
    render(<SettingsPanel onClose={vi.fn()} />)
    const toggle = screen.getByRole('switch', { name: '任务规划模型使用独立模型' })

    await user.click(screen.getByText('任务规划模型（Planner）'))
    expect(toggle).not.toBeChecked()
    expect(screen.queryByLabelText('任务规划模型（Planner） API Key')).not.toBeInTheDocument()

    await user.click(toggle)
    expect(toggle).toBeChecked()
    expect(screen.getByLabelText('任务规划模型（Planner） API Key')).toBeInTheDocument()
  })

  it('shows configured key status inline with the API Key label', async () => {
    render(<SettingsPanel onClose={vi.fn()} />)
    const input = await screen.findByLabelText('默认模型（必填） API Key')
    const label = input.closest('label')

    await waitFor(() => expect(label).toHaveTextContent('API Key已配置 sk-***123'))
    expect(label?.querySelector('.field-label-row')).not.toBeNull()
  })
})
