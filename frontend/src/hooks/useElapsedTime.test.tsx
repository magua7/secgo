import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useElapsedTime } from './useElapsedTime'

describe('useElapsedTime', () => {
  afterEach(() => vi.useRealTimers())

  it('ticks independently while running and freezes at the terminal timestamp', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-21T08:01:09.000Z'))
    const startedAt = Date.now() - 69_000
    const { result, rerender } = renderHook(
      ({ running, endedAt }) => useElapsedTime(startedAt, endedAt, running),
      { initialProps: { running: true, endedAt: null as number | null } },
    )

    expect(result.current).toBe(69_000)
    act(() => {
      vi.advanceTimersByTime(1_000)
    })
    expect(result.current).toBe(70_000)

    const endedAt = Date.now()
    rerender({ running: false, endedAt })
    act(() => {
      vi.advanceTimersByTime(60_000)
    })
    expect(result.current).toBe(70_000)
  })
})
