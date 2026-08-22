import { describe, expect, it } from 'vitest'
import { distanceToBottom, isNearBottom, shouldFollowStreamUpdate } from './autoFollow'

describe('conversation auto follow', () => {
  it('computes distance to bottom and uses a 100px proximity threshold', () => {
    expect(distanceToBottom({ scrollHeight: 1000, scrollTop: 700, clientHeight: 200 })).toBe(100)
    expect(isNearBottom({ scrollHeight: 1000, scrollTop: 721, clientHeight: 200 })).toBe(true)
    expect(isNearBottom({ scrollHeight: 1000, scrollTop: 700, clientHeight: 200 })).toBe(false)
  })


  it('keeps following from the pre-render position even when new content enlarges the page', () => {
    const before = { scrollHeight: 1000, scrollTop: 751, clientHeight: 200 }
    const after = { scrollHeight: 1100, scrollTop: 751, clientHeight: 200 }
    const wasFollowing = isNearBottom(before)
    expect(wasFollowing).toBe(true)
    expect(isNearBottom(after)).toBe(false)
    expect(shouldFollowStreamUpdate(wasFollowing)).toBe(true)
  })
})
