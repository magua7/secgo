import { useEffect, useState } from 'react'

export function useElapsedTime(startedAt: number | null, endedAt: number | null, running: boolean): number | null {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!running || startedAt === null) return undefined
    setNow(Date.now())
    const timer = window.setInterval(() => setNow(Date.now()), 1_000)
    return () => window.clearInterval(timer)
  }, [running, startedAt])

  if (startedAt === null) return null
  const effectiveEnd = running ? now : endedAt ?? now
  return Math.max(0, effectiveEnd - startedAt)
}
