import { SSE_EVENT_NAMES, type ExecutionEvent, type SseEventName } from '../types/events'

export function acceptEventId(lastSeen: number, rawId: string): { accepted: boolean; lastSeen: number } {
  const id = Number.parseInt(rawId, 10)
  if (!Number.isFinite(id)) return { accepted: true, lastSeen }
  if (id <= lastSeen) return { accepted: false, lastSeen }
  return { accepted: true, lastSeen: id }
}

export function parseEventData(raw: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(raw)
    return parsed !== null && typeof parsed === 'object' ? parsed as Record<string, unknown> : null
  } catch { return null }
}

export interface StreamCallbacks {
  onEvent: (event: ExecutionEvent) => void
  onOpen: () => void
  onReconnect: () => void
  onAuthProbe: () => void
}

export function connectExecutionStream(sessionId: string, callbacks: StreamCallbacks): () => void {
  const source = new EventSource(`/api/events?sessionId=${encodeURIComponent(sessionId)}`)
  let lastSeen = 0
  let errors = 0
  SSE_EVENT_NAMES.forEach((name: SseEventName) => {
    source.addEventListener(name, (rawEvent) => {
      const event = rawEvent as MessageEvent<string>
      const accepted = acceptEventId(lastSeen, event.lastEventId)
      if (!accepted.accepted) return
      lastSeen = accepted.lastSeen
      const data = parseEventData(event.data)
      if (data) callbacks.onEvent({ type: name, data } as ExecutionEvent)
    })
  })
  source.onopen = () => { errors = 0; callbacks.onOpen() }
  source.onerror = () => {
    errors += 1
    callbacks.onReconnect()
    if (errors >= 2) { errors = 0; callbacks.onAuthProbe() }
  }
  return () => source.close()
}
