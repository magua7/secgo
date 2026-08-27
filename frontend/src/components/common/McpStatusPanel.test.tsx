import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { McpStatus } from '../../services/api'
import { McpStatusPanel } from './McpStatusPanel'

const apiMocks = vi.hoisted(() => ({
  getMcpStatus: vi.fn(),
  handleApiError: vi.fn((error: unknown) => error instanceof Error ? error.message : '错误'),
}))

vi.mock('../../services/api', () => apiMocks)

const offlineStatus = (overrides: Partial<McpStatus> = {}): McpStatus => ({
  running: false,
  connected: false,
  server_count: 0,
  servers: [],
  tool_count: 0,
  tools: [],
  configured: false,
  ...overrides,
})

beforeEach(() => {
  apiMocks.getMcpStatus.mockReset().mockResolvedValue(offlineStatus())
})

afterEach(cleanup)

describe('McpStatusPanel', () => {
  it('renders layered status cells instead of a raw concatenated line', async () => {
    render(<McpStatusPanel />)
    expect(await screen.findByText('未连接')).toBeInTheDocument()
    expect(screen.getByText('连接状态')).toBeInTheDocument()
    expect(screen.getByText('MCP 服务')).toBeInTheDocument()
    expect(screen.getByText('可用工具')).toBeInTheDocument()
    expect(screen.queryByText(/server:\s*0/)).not.toBeInTheDocument()
    expect(screen.queryByText(/tools:\s*0/)).not.toBeInTheDocument()
  })

  it('shows a soft hint when MCP is not configured', async () => {
    render(<McpStatusPanel />)
    await waitFor(() => expect(apiMocks.getMcpStatus).toHaveBeenCalled())
    const hint = screen.getByText(/未检测到 MCP 配置/)
    expect(hint.textContent).toContain('config/mcp.jsonc')
    expect(hint.textContent).toContain('MCP_SERVER_COMMAND')
  })

  it('uses a formal 刷新状态 button that re-probes the backend', async () => {
    const user = userEvent.setup()
    apiMocks.getMcpStatus.mockResolvedValue(offlineStatus({ configured: true, connected: true, server_count: 2, tool_count: 5, servers: [{ name: 'fs', connected: true, tool_count: 5 }], tools: ['mcp_fs_read'] }))
    render(<McpStatusPanel />)
    const refresh = await screen.findByRole('button', { name: /刷新状态/ })
    await user.click(refresh)
    await waitFor(() => expect(apiMocks.getMcpStatus).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('已连接')).toBeInTheDocument()
    expect(screen.getByText('fs')).toBeInTheDocument()
    expect(screen.getByText(/工具清单（1）/i)).toBeInTheDocument()
  })

  it('presents probe failures as an error card', async () => {
    apiMocks.getMcpStatus.mockRejectedValue(new Error('后端不可达'))
    render(<McpStatusPanel />)
    expect(await screen.findByRole('alert')).toHaveTextContent('MCP 状态获取失败')
    expect(screen.getByText('后端不可达')).toBeInTheDocument()
  })
})
