import { describe, expect, it } from 'vitest'
import { normalizePanelMode, normalizeTheme } from './preferences'

describe('stored preferences', () => {
  it('accepts only supported themes and panel modes', () => {
    expect(normalizeTheme('dark')).toBe('dark')
    expect(normalizeTheme('neon')).toBeNull()
    expect(normalizePanelMode('compact')).toBe('expanded')
    expect(normalizePanelMode('hidden')).toBe('hidden')
    expect(normalizePanelMode('wide')).toBeNull()
  })
})
