import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'

vi.mock('../pages/WorkspacePage', () => ({
  WorkspacePage: ({ rightVisible, setRightVisible }: { rightVisible: boolean; setRightVisible: (v: boolean) => void }) => (
    <div data-testid="workspace-stub" data-right-visible={rightVisible}>
      <button onClick={() => setRightVisible(false)}>collapse-stub</button>
    </div>
  ),
}))
vi.mock('../pages/HomePage', () => ({ HomePage: () => <div data-testid="home-stub" /> }))

function mockMatchMedia() {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia
}

function setHash(hash: string) {
  window.history.replaceState(null, '', hash)
}

afterEach(cleanup)
beforeEach(() => {
  localStorage.clear()
  mockMatchMedia()
})

describe('App shell nav alignment', () => {
  it('centers nav on the viewport for the home page', () => {
    setHash('#/')
    render(<App />)
    const shell = document.querySelector('.app-shell') as HTMLElement
    expect(shell.style.getPropertyValue('--shell-left-width')).toBe('0px')
    expect(shell.style.getPropertyValue('--shell-right-width')).toBe('0px')
    expect(screen.getByTestId('home-stub')).toBeInTheDocument()
  })

  it('uses left=250 and right=expanded-var for workspace with the panel visible', () => {
    setHash('#/workspace')
    render(<App />)
    const shell = document.querySelector('.app-shell') as HTMLElement
    expect(shell.style.getPropertyValue('--shell-left-width')).toBe('250px')
    expect(shell.style.getPropertyValue('--shell-right-width')).toBe('var(--workspace-right-expanded)')
  })

  it('shares rightVisible between the TopBar shell vars and WorkspacePage', async () => {
    setHash('#/workspace')
    render(<App />)
    const shell = document.querySelector('.app-shell') as HTMLElement
    expect(screen.getByTestId('workspace-stub')).toHaveAttribute('data-right-visible', 'true')
    expect(shell.style.getPropertyValue('--shell-right-width')).toBe('var(--workspace-right-expanded)')

    await userEvent.click(screen.getByRole('button', { name: 'collapse-stub' }))
    expect(screen.getByTestId('workspace-stub')).toHaveAttribute('data-right-visible', 'false')
    expect(shell.style.getPropertyValue('--shell-right-width')).toBe('0px')
  })
})
