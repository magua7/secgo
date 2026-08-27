import { useEffect, useState } from 'react'
import { getMcpStatus, handleApiError, type McpStatus } from '../../services/api'
import { Icon } from './Icon'

export function McpStatusPanel() {
  const [status, setStatus] = useState<McpStatus | null>(null)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState(false)

  const load = () => {
    setStatus(null); setError('')
    getMcpStatus().then(setStatus).catch((reason) => setError(handleApiError(reason)))
  }

  useEffect(() => { load() }, [])

  return <section className="settings-section mcp-status-section">
    <div className="section-title-row"><h2>工具扩展 / MCP</h2><button type="button" className="text-button" onClick={load}>刷新</button></div>
    <p>查看 Model Context Protocol 服务器连接状态与可用工具。工具由后端自动发现并注入各 Agent。</p>

    {error && <p className="hero-error">{error}</p>}

    {!status && !error && <p className="mcp-loading">正在检测 MCP 状态…</p>}

    {status && <>
      <div className="mcp-summary">
        <span className={status.connected ? 'mcp-badge ok' : 'mcp-badge off'}>
          <i /> {status.connected ? '已连接' : '未连接'}
        </span>
        <span>server: {status.server_count} · tools: {status.tool_count}</span>
        {!status.configured && <small className="mcp-hint">未检测到 MCP 配置（config/mcp.jsonc 或 MCP_SERVER_COMMAND）</small>}
      </div>

      {status.servers.length > 0 && <div className="mcp-servers">
        {status.servers.map((server) => <article key={server.name} className="mcp-server">
          <span className="mcp-server-name"><i className={server.connected ? 'ok' : 'off'} />{server.name}</span>
          <small>{server.tool_count} 个工具</small>
        </article>)}
      </div>}

      {status.tools.length > 0 && <button type="button" className="mcp-tool-toggle" onClick={() => setExpanded((value) => !value)}>
        {expanded ? '收起' : '展开'}工具清单（{status.tools.length}）
      </button>}
      {expanded && status.tools.length > 0 && <ul className="mcp-tools">
        {status.tools.map((tool) => <li key={tool}><Icon name="tool" />{tool}</li>)}
      </ul>}
    </>}
  </section>
}
