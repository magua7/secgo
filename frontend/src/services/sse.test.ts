import { describe, expect, it } from 'vitest'
import { acceptEventId, parseEventData } from './sse'

describe('SSE adapter', () => {
  it('deduplicates replayed numeric event ids', () => {
    expect(acceptEventId(4, '5')).toEqual({ accepted: true, lastSeen: 5 })
    expect(acceptEventId(5, '5')).toEqual({ accepted: false, lastSeen: 5 })
    expect(acceptEventId(5, '')).toEqual({ accepted: true, lastSeen: 5 })
  })

  it('returns null for malformed JSON rather than crashing the stream', () => {
    expect(parseEventData('{bad')).toBeNull()
    expect(parseEventData('{"chunk":"ok"}')).toEqual({ chunk: 'ok' })
  })
})
