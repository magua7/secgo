import { describe, expect, it } from 'vitest'
import { RIGHT_EXPANDED_VAR, shellPanelVars, WORKSPACE_LEFT_WIDTH } from './shellLayout'

describe('shellPanelVars', () => {
  it('centers nav on the viewport for home (no side panels)', () => {
    expect(shellPanelVars(false, true)).toEqual({
      '--shell-left-width': '0px',
      '--shell-right-width': '0px',
    })
  })

  it('sets left=250 and right=expanded-var for workspace with the right panel visible', () => {
    expect(WORKSPACE_LEFT_WIDTH).toBe('250px')
    expect(shellPanelVars(true, true)).toEqual({
      '--shell-left-width': '250px',
      '--shell-right-width': RIGHT_EXPANDED_VAR,
    })
    // --workspace-right-expanded 由 globals.css 定义：默认 340px，<=1280px 时 300px。
    expect(RIGHT_EXPANDED_VAR).toBe('var(--workspace-right-expanded)')
  })

  it('sets left=250 and right=0 for workspace with the right panel collapsed', () => {
    expect(shellPanelVars(true, false)).toEqual({
      '--shell-left-width': '250px',
      '--shell-right-width': '0px',
    })
  })
})
