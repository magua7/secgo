import { describe, expect, it } from 'vitest'
import { normalizeTheme } from './preferences'

describe('stored preferences', () => {
  it('accepts only supported themes', () => {
    expect(normalizeTheme('dark')).toBe('dark')
    expect(normalizeTheme('neon')).toBeNull()
  })
})
