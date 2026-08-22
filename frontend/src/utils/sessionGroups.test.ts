import { describe, expect, it } from 'vitest'
import { groupSessionsByDate } from './sessionGroups'

describe('groupSessionsByDate', () => {
  it('groups sessions into today, yesterday and earlier', () => {
    const now = new Date('2026-08-21T12:00:00+08:00').getTime()
    const sessions = [
      { id: 'a', title: 'today', messageCount: 1, stepCount: 1, createdAt: now, updatedAt: now },
      { id: 'b', title: 'yesterday', messageCount: 1, stepCount: 1, createdAt: now, updatedAt: now - 86_400_000 },
      { id: 'c', title: 'earlier', messageCount: 1, stepCount: 1, createdAt: now, updatedAt: now - 172_800_000 },
    ]
    const groups = groupSessionsByDate(sessions, new Date(now))
    expect(groups.map((group) => [group.label, group.sessions.length])).toEqual([
      ['今天', 1], ['昨天', 1], ['更早', 1],
    ])
  })
  it('normalizes backend seconds, ISO values and sorts by latest activity', () => {
    const now = new Date('2026-08-21T12:00:00+08:00')
    const seconds = Math.floor(now.getTime() / 1000)
    const sessions = [
      { id: 'old', title: 'old', messageCount: 1, stepCount: 1, createdAt: seconds - 30, updatedAt: seconds - 30 },
      { id: 'new', title: 'new', messageCount: 1, stepCount: 1, createdAt: now.toISOString(), updatedAt: now.toISOString() },
    ]
    expect(groupSessionsByDate(sessions, now)[0]?.sessions.map((item) => item.id)).toEqual(['new', 'old'])
  })
})
