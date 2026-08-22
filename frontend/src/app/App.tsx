import { useEffect, useState } from 'react'
import { SettingsPanel } from '../components/common/SettingsPanel'
import { useTheme } from '../hooks/preferences'
import { HomePage } from '../pages/HomePage'
import { WorkspacePage } from '../pages/WorkspacePage'

export function App() {
  const { theme, toggleTheme } = useTheme()
  const [hash, setHash] = useState(window.location.hash || '#/')
  const [settings, setSettings] = useState(false)
  useEffect(() => { const update = () => setHash(window.location.hash || '#/'); window.addEventListener('hashchange', update); return () => window.removeEventListener('hashchange', update) }, [])
  return <>{hash.startsWith('#/workspace')
    ? <WorkspacePage theme={theme} onThemeToggle={toggleTheme} onOpenSettings={() => setSettings(true)} />
    : <HomePage theme={theme} onThemeToggle={toggleTheme} onOpenSettings={() => setSettings(true)} />}
    {settings && <SettingsPanel theme={theme} onThemeToggle={toggleTheme} onClose={() => setSettings(false)} />}
  </>
}
