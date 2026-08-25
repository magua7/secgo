export interface SessionSummary {
  id: string
  title: string
  messageCount: number
  stepCount: number
  createdAt: number | string | null
  updatedAt: number | string | null
}

export interface HistoryMessage {
  kind: 'user' | 'assistant' | 'tool'
  text: string
}

export interface SessionMessagesResponse {
  sessionId: string
  messages: HistoryMessage[]
  todoList: TodoItem[]
}

export interface TodoItem {
  text: string
  done: boolean
}

export interface SessionGroup {
  label: '今天' | '昨天' | '更早'
  sessions: SessionSummary[]
}
