import type { MessageAttachment } from './attachment'
import type { RunSnapshot } from './snapshot'

export type SessionStatus = 'idle' | 'queued' | 'running' | 'awaiting_user' | 'completed' | 'stopped' | 'error'

export interface SessionSummary {
  id: string
  title: string
  messageCount: number
  stepCount: number
  status?: SessionStatus
  createdAt: number | string | null
  updatedAt: number | string | null
}

export interface HistoryMessage {
  kind: 'user' | 'assistant' | 'tool'
  text: string
  attachments?: MessageAttachment[]
  createdAt?: number
}

// 服务端 conversation_turns 表返回的持久化 Turn（每个 Turn 独立 execution snapshot）
export interface PersistedTurn {
  id: string
  sessionId?: string
  sequence: number
  kind: 'direct_response' | 'agent_task' | string
  userMessage: { text: string; attachments?: MessageAttachment[] } | null
  assistantAnswer: string | null
  execution: RunSnapshot | null
  status: string
  createdAt: number | null
  updatedAt: number | null
}

export interface SessionConversationResponse {
  sessionId: string
  status: string
  turns: PersistedTurn[]
}

export interface TodoItem {
  text: string
  done: boolean
}

export interface SessionGroup {
  label: '今天' | '昨天' | '更早'
  sessions: SessionSummary[]
}
