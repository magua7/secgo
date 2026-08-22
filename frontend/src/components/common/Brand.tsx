import logo from '../../assets/secgo-logo.png'

export function Brand({ compact = false }: { compact?: boolean }) {
  return <div className={`brand ${compact ? 'brand-compact' : ''}`}>
    <img src={logo} alt="SEC-GO 狼盾标识" />
    {!compact && <div><strong>SEC-GO</strong><span>安全智能体</span></div>}
  </div>
}
