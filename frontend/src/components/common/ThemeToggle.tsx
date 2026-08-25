import type { Theme } from '../../hooks/preferences'
import { Icon } from './Icon'

export function ThemeToggle({ theme, onToggle }: { theme: Theme; onToggle: () => void }) {
  return <button className="theme-toggle" onClick={onToggle} aria-label={theme === 'light' ? '切换至深色主题' : '切换至浅色主题'}>
    <span className={theme === 'light' ? 'active' : ''}><Icon name="sun" /></span>
    <span className={theme === 'dark' ? 'active' : ''}><Icon name="moon" /></span>
  </button>
}
