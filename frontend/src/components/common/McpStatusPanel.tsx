import { useEffect, useState } from 'react'
import { getMcpStatus, handleApiError, type McpStatus } from '../../services/api'
import { Icon } from './Icon'

/** 设置页「工具 / MCP」状态卡片：标题区 + 说明区 + 分层状态块，替代原裸文本拼行展示。 */
export function McpStatusPanel() {
  const [status, setStatus] = useState<McpStatus | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState(false)

  const load = () => {
    setLoading(true)
    setStatus(null)
    setError('')
    getMcpStatus()
      .then((value) => { setStatus(value) })
      .catch((reason) => setError(handleApiError(reason)))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  return <section className="settings-section mcp-status-section">
    <div className="section-title-row">
      <h2>工具扩展 / MCP</h2>
      <button type="button" className={`mcp-refresh-btn ${loading ? 'loading' : ''}`} onClick={load} disabled={loading}>
        <Icon name="tool" /> 刷新状态
      </button>
    </div>
    <p className="mcp-desc">查看 Model Context Protocol 服务连接状态与可用工具。</p>
    <p className="mcp-desc">系统会自动发现并接入已配置的 MCP 服务。</p>

    {error && <div className="mcp-error" role="alert">
      <strong>MCP 状态获取失败</strong>
      <span>{error}</span>
    </div>}

    {!status && !error && <div className="mcp-loading" aria-live="polite"><i className="mcp-indicator pending" /><span>正在检测 MCP 服务…</span></div>}

    {status && <>
      <div className="mcp-status-grid" role="list">
        <div className="mcp-cell" role="listitem">
          <small>连接状态</small>
          <strong><i className={`mcp-indicator ${status.connected ? 'ok' : 'off'}`} />{status.connected ? '已连接' : '未连接'}</strong>
        </div>
        <div className="mcp-cell" role="listitem">
          <small>MCP 服务</small>
          <strong>{status.server_count}<em> 个</em></strong>
        </div>
        <div className="mcp-cell" role="listitem">
          <small>可用工具</small>
          <strong>{status.tool_count}<em> 个</em></strong>
        </div>
      </div>

      {!status.configured && <p className="mcp-hint">未检测到 MCP 配置。请在 config/mcp.jsonc 中添加服务，或通过 MCP_SERVER_COMMAND 指定启动命令。</p>}

      {status.servers.length > 0 && <div className="mcp-servers">
        {status.servers.map((server) => <article key={server.name} className="mcp-server-card">
          <span className="mcp-server-name"><i className={`mcp-indicator ${server.connected ? 'ok' : 'off'}`} />{server.name}</span>
          <small>{server.tool_count} 个工具{server.connected ? '' : ' · 未连接'}</small>
        </article>)}
      </div>}

      {status.tools.length > 0 && <>
        <button type="button" className="mcp-tool-toggle" onClick={() => setExpanded((value) => !value)}>
          {expanded ? '收起' : '展开'}工具清单（{status.tools.length}）
        </button>
        {expanded && <ul className="mcp-tools">
          {status.tools.map((tool) => <li key={tool}><Icon name="tool" />{tool}</li>)}
        </ul>}
      </>}
    </>}
  </section>
}
