import type { SessionGroup, SessionSummary } from '../types/session'

const dayStart = (date: Date): number => new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()

export function parseActivityTimestamp(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null
  const numeric = typeof value === 'number' ? value : Number(value)
  if (Number.isFinite(numeric)) return numeric < 100_000_000_000 ? numeric * 1000 : numeric
  const parsed = Date.parse(String(value))
  return Number.isFinite(parsed) ? parsed : null
}

export function groupSessionsByDate(sessions: SessionSummary[], now = new Date()): SessionGroup[] {
  const today = dayStart(now)
  const yesterday = today - 86_400_000
  const buckets: Record<SessionGroup['label'], SessionSummary[]> = { 今天: [], 昨天: [], 更早: [] }
  const sorted = [...sessions].sort((a, b) => (parseActivityTimestamp(b.updatedAt ?? b.createdAt) ?? -Infinity) - (parseActivityTimestamp(a.updatedAt ?? a.createdAt) ?? -Infinity))
  sorted.forEach((session) => {
    const timestamp = parseActivityTimestamp(session.updatedAt ?? session.createdAt)
    if (timestamp === null) { console.warn('[SEC-GO] 会话时间字段无效，暂归入今天', session.id); buckets.今天.push(session); return }
    if (timestamp >= today) buckets.今天.push(session)
    else if (timestamp >= yesterday) buckets.昨天.push(session)
    else buckets.更早.push(session)
  })
  return (['今天', '昨天', '更早'] as const).map((label) => ({ label, sessions: buckets[label] }))
}
