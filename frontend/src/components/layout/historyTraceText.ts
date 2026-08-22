const HISTORY_DETAIL_LIMIT = 12_000
const TRUNCATED_SUFFIX = '\n\n[内容过长，已截断]'

export function normalizeHistoryTraceText(value: string): string {
  const unwrapped = unwrapSerializedOutput(value)
  const normalized = unwrapped
    .replace(/\\r\\n/g, '\n')
    .replace(/\\n/g, '\n')
    .replace(/\r\n?/g, '\n')

  if (normalized.length <= HISTORY_DETAIL_LIMIT) return normalized
  return `${normalized.slice(0, HISTORY_DETAIL_LIMIT)}${TRUNCATED_SUFFIX}`
}

function unwrapSerializedOutput(value: string): string {
  let current: unknown = value.trim()
  for (let depth = 0; depth < 2; depth += 1) {
    if (typeof current !== 'string') break
    const serialized = current
    try {
      current = JSON.parse(serialized) as unknown
    } catch {
      return serialized
    }
  }
  if (typeof current === 'string') return current
  if (current && typeof current === 'object' && 'output' in current) {
    const output = (current as { output?: unknown }).output
    if (typeof output === 'string') return unwrapSerializedOutput(output)
  }
  try { return JSON.stringify(current, null, 2) } catch { return value }
}

export function describeHistoricalToolOutput(value: string): { title: string; detail: string } {
  const match = value.match(/^\[工具结果(?:\s+([^\]]+))?\]\s*:?\s*/u)
  const toolName = match?.[1]?.trim()
  const detail = normalizeHistoryTraceText(match ? value.slice(match[0].length) : value)
  return { title: toolName ? `工具输出 · ${toolName}` : '已保存的工具输出', detail }
}
