import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { SessionSummary } from '../../types/session'
import { Sidebar } from './Sidebar'

afterEach(cleanup)

const sessions: SessionSummary[] = [
  { id: 'session-a', title: '会话 A', messageCount: 1, stepCount: 1, createdAt: Date.now(), updatedAt: Date.now() },
  { id: 'session-b', title: '会话 B', messageCount: 1, stepCount: 1, createdAt: Date.now(), updatedAt: Date.now() },
]

const rect = (top: number, bottom: number, right = 220): DOMRect => ({
  x: right - 24, y: top, width: 24, height: bottom - top, top, right, bottom, left: right - 24,
  toJSON: () => ({}),
})

function renderSidebar(overrides: Partial<React.ComponentProps<typeof Sidebar>> = {}) {
  const props = {
    sessions,
    currentId: null,
    onNew: vi.fn(),
    onSelect: vi.fn(),
    onRename: vi.fn(),
    onDelete: vi.fn(),
    onSettings: vi.fn(),
    ...overrides,
  }
  render(<Sidebar {...props} />)
  const triggers = screen.getAllByRole('button', { name: '会话操作' })
  vi.spyOn(triggers[0]!, 'getBoundingClientRect').mockReturnValue(rect(100, 124))
  vi.spyOn(triggers[1]!, 'getBoundingClientRect').mockReturnValue(rect(150, 174))
  return { props, triggers }
}

describe('Sidebar session context menu', () => {
  it('opens A, replaces it with B, and only renders one menu', async () => {
    const { triggers } = renderSidebar()
    await userEvent.click(triggers[0]!)
    expect(screen.getByRole('menu')).toBeInTheDocument()
    expect(screen.getByRole('menu').parentElement).toBe(document.body)
    expect(triggers[0]).toHaveAttribute('aria-expanded', 'true')

    await userEvent.click(triggers[1]!)
    expect(screen.getAllByRole('menu')).toHaveLength(1)
    expect(triggers[0]).toHaveAttribute('aria-expanded', 'false')
    expect(triggers[1]).toHaveAttribute('aria-expanded', 'true')
  })

  it('closes when the same trigger is clicked again', async () => {
    const { triggers } = renderSidebar()
    await userEvent.click(triggers[0]!)
    await userEvent.click(triggers[0]!)
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('closes on outside pointer down', async () => {
    const { triggers } = renderSidebar()
    await userEvent.click(triggers[0]!)
    fireEvent.pointerDown(document.body)
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('closes on Escape and restores trigger focus', async () => {
    const { triggers } = renderSidebar()
    await userEvent.click(triggers[0]!)
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    expect(triggers[0]).toHaveFocus()
  })

  it('closes before invoking Rename exactly once for the active session', async () => {
    const onRename = vi.fn()
    const { triggers } = renderSidebar({ onRename })
    await userEvent.click(triggers[0]!)
    await userEvent.click(screen.getByRole('menuitem', { name: '重命名' }))
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    expect(onRename).toHaveBeenCalledTimes(1)
    expect(onRename).toHaveBeenCalledWith(sessions[0])
  })

  it('closes before invoking Delete exactly once for the active session', async () => {
    const onDelete = vi.fn()
    const { triggers } = renderSidebar({ onDelete })
    await userEvent.click(triggers[1]!)
    await userEvent.click(screen.getByRole('menuitem', { name: '删除' }))
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    expect(onDelete).toHaveBeenCalledTimes(1)
    expect(onDelete).toHaveBeenCalledWith(sessions[1])
  })

  it('flips above when the trigger is near the viewport bottom', async () => {
    const { triggers } = renderSidebar()
    vi.spyOn(triggers[0]!, 'getBoundingClientRect').mockReturnValue(rect(window.innerHeight - 30, window.innerHeight - 6))
    await userEvent.click(triggers[0]!)
    expect(screen.getByRole('menu')).toHaveAttribute('data-placement', 'above')
  })

  it('closes on list scroll, resize, and session selection', async () => {
    const onSelect = vi.fn()
    const { triggers } = renderSidebar({ onSelect })
    await userEvent.click(triggers[0]!)
    fireEvent.scroll(document.querySelector('.session-list')!)
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()

    await userEvent.click(triggers[0]!)
    fireEvent(window, new Event('resize'))
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()

    await userEvent.click(triggers[0]!)
    await userEvent.click(screen.getByRole('button', { name: /会话 B/ }))
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    expect(onSelect).toHaveBeenCalledWith('session-b')
  })
})
