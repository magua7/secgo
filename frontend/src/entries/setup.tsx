import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { SettingsPage } from '../pages/SettingsPage'
import { normalizeTheme } from '../hooks/preferences'
import '../styles/tokens.css'
import '../styles/globals.css'

document.documentElement.dataset.theme = normalizeTheme(localStorage.getItem('secgo.theme')) ?? 'light'
createRoot(document.getElementById('root')!).render(<StrictMode><SettingsPage /></StrictMode>)
