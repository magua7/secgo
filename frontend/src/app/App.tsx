import { useEffect, useState } from 'react'
import { SettingsPanel } from '../components/common/SettingsPanel'
// 导入现成的TopBar
import { TopBar } from '../components/layout/TopBar'
import { useTheme } from '../hooks/preferences'
import { HomePage } from '../pages/HomePage'
import { WorkspacePage } from '../pages/WorkspacePage'



export function App() {
  const { theme, toggleTheme } = useTheme()
  const [hash, setHash] = useState(window.location.hash || '#/')
  const [settings, setSettings] = useState(false)


  useEffect(() => {
    const update = () => setHash(window.location.hash || '#/')
    window.addEventListener('hashchange', update)
    return () => window.removeEventListener('hashchange', update)
  }, [])


  // 判断当前路由，传给TopBar做高亮
  const activeNav = hash.startsWith('#/workspace') ? 'workspace' : 'home'


  return (
  <div style={{ display: "flex", flexDirection: "column", height: "100vh", width: "100vw", overflow: "hidden" }}>
    <TopBar
      theme={theme}
      active={activeNav}
      onThemeToggle={toggleTheme}
      onOpenSettings={() => setSettings(true)}
    />

    <div style={{ flex: 1, overflow: "hidden" }}>
      {hash.startsWith('#/workspace')
        ? <WorkspacePage />
        : <HomePage />
      }
    </div>

    {settings && <SettingsPanel theme={theme} onThemeToggle={toggleTheme} onClose={() => setSettings(false)} />}
  </div>
)

}
