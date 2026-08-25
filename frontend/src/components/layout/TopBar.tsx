import type { Theme } from '../../hooks/preferences'
import { Brand } from '../common/Brand'
import { Icon } from '../common/Icon'
import { ThemeToggle } from '../common/ThemeToggle'

interface Props { theme: Theme; active: 'home' | 'workspace'; onThemeToggle: () => void; onOpenSettings: () => void }

export function TopBar({ theme, active, onThemeToggle, onOpenSettings }: Props) {
  const go = (hash: string) => { window.location.hash = hash }
  return <header className="topbar">
    <Brand />
    <nav aria-label="主导航">
      <button className={active === 'home' ? 'active' : ''} onClick={() => go('#/')}>首页</button>
      <button className={active === 'workspace' ? 'active' : ''} onClick={() => go('#/workspace')}>工作台</button>
    </nav>
    <div className="topbar-actions">
      <span className="online"><i />在线</span>
      <ThemeToggle theme={theme} onToggle={onThemeToggle} />
      <span className="user-label"><Icon name="user" />用户</span>
      <button className="icon-button" onClick={onOpenSettings} aria-label="打开设置"><Icon name="settings" /></button>
    </div>
  </header>
}
