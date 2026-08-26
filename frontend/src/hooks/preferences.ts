import { useEffect, useState } from 'react'

export type Theme = 'light' | 'dark'

export const normalizeTheme = (value: string | null): Theme | null => value === 'light' || value === 'dark' ? value : null

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => normalizeTheme(localStorage.getItem('secgo.theme')) ?? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'))
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('secgo.theme', theme)
  }, [theme])
  return { theme, setTheme, toggleTheme: () => setTheme((value) => value === 'light' ? 'dark' : 'light') }
}

export function usePanelPreferences() {
  const [rightVisible, setRightVisible] = useState(() => localStorage.getItem('secgo.rightPanel') !== 'hidden')
  useEffect(() => localStorage.setItem('secgo.rightPanel', rightVisible ? 'expanded' : 'hidden'), [rightVisible])
  return { rightVisible, setRightVisible }
}
