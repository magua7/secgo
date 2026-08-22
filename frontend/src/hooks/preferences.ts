import { useEffect, useState } from 'react'

export type Theme = 'light' | 'dark'
export type LeftPanelMode = 'expanded' | 'hidden'

export const normalizeTheme = (value: string | null): Theme | null => value === 'light' || value === 'dark' ? value : null
export const normalizePanelMode = (value: string | null): LeftPanelMode | null => value === 'compact' ? 'expanded' : value === 'expanded' || value === 'hidden' ? value : null

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => normalizeTheme(localStorage.getItem('secgo.theme')) ?? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'))
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('secgo.theme', theme)
  }, [theme])
  return { theme, setTheme, toggleTheme: () => setTheme((value) => value === 'light' ? 'dark' : 'light') }
}

export function usePanelPreferences() {
  const [leftMode, setLeftMode] = useState<LeftPanelMode>(() => normalizePanelMode(localStorage.getItem('secgo.leftPanel')) ?? 'expanded')
  const [rightVisible, setRightVisible] = useState(() => localStorage.getItem('secgo.rightPanel') !== 'hidden')
  useEffect(() => localStorage.setItem('secgo.leftPanel', leftMode), [leftMode])
  useEffect(() => localStorage.setItem('secgo.rightPanel', rightVisible ? 'expanded' : 'hidden'), [rightVisible])
  const cycleLeft = () => setLeftMode((value) => value === 'expanded' ? 'hidden' : 'expanded')
  return { leftMode, setLeftMode, cycleLeft, rightVisible, setRightVisible }
}
