import { useCallback, useEffect, useMemo, useReducer, useRef } from 'react'
import { createInitialExecutionState, executionReducer } from '../state/executionReducer'
import type { ExecutionState } from '../types/execution'
import type { ExecutionEvent } from '../types/events'
import { getKeysStatus, handleApiError } from '../services/api'
import { connectExecutionStream } from '../services/sse'

export type ConnectionStatus = 'idle' | 'connected' | 'reconnecting'

export interface RuntimeEntry {
  state: ExecutionState
  connection: ConnectionStatus
}

interface RegistryState {
  selectedId: string | null
  runtimes: Record<string, RuntimeEntry>
}

type RegistryAction =
  | { type: 'select'; sessionId: string | null }
  | { type: 'ensure'; sessionId: string }
  | { type: 'event'; sessionId: string; event: ExecutionEvent }
  | { type: 'reset'; sessionId: string }
  | { type: 'toggle'; sessionId: string }
  | { type: 'connection'; sessionId: string; connection: ConnectionStatus }

const initialRegistry = (): RegistryState => ({ selectedId: null, runtimes: {} })

function ensureEntry(state: RegistryState, sessionId: string): RegistryState {
  if (state.runtimes[sessionId]) return state
  return { ...state, runtimes: { ...state.runtimes, [sessionId]: { state: createInitialExecutionState(), connection: 'idle' } } }
}

function registryReducer(state: RegistryState, action: RegistryAction): RegistryState {
  switch (action.type) {
    case 'select':
      return state.selectedId === action.sessionId ? state : { ...state, selectedId: action.sessionId }
    case 'ensure':
      return ensureEntry(state, action.sessionId)
    case 'event': {
      const entry = state.runtimes[action.sessionId] ?? { state: createInitialExecutionState(), connection: 'idle' }
      return { ...state, runtimes: { ...state.runtimes, [action.sessionId]: { ...entry, state: executionReducer(entry.state, action.event) } } }
    }
    case 'reset':
      return { ...state, runtimes: { ...state.runtimes, [action.sessionId]: { state: createInitialExecutionState(), connection: 'idle' } } }
    case 'toggle': {
      const entry = state.runtimes[action.sessionId]
      if (!entry) return state
      return { ...state, runtimes: { ...state.runtimes, [action.sessionId]: { ...entry, state: { ...entry.state, executionExpanded: !entry.state.executionExpanded } } } }
    }
    case 'connection': {
      const entry = state.runtimes[action.sessionId]
      if (!entry) return state
      return { ...state, runtimes: { ...state.runtimes, [action.sessionId]: { ...entry, connection: action.connection } } }
    }
  }
}

/**
 * 每个 session 一个独立 ExecutionState + SSE 生命周期。
 * selectedId 只表示「当前正在查看哪个会话」，与后台运行/SSE 生命周期解耦：
 * 切换会话只改 selectedId，绝不 reset 其他 runtime、绝不关闭其 SSE。
 * （每个 Turn 的历史真相在服务端 conversation_turns，这里只维护「当前运行 turn」的实时态。）
 */
export function useExecutionRegistry() {
  const [registry, dispatch] = useReducer(registryReducer, undefined, initialRegistry)
  const connections = useRef(new Map<string, () => void>())
  const started = useRef(new Set<string>())

  useEffect(() => () => {
    connections.current.forEach((cleanup) => cleanup())
    connections.current.clear()
    started.current.clear()
  }, [])

  const startSession = useCallback((sessionId: string) => {
    dispatch({ type: 'ensure', sessionId })
    if (started.current.has(sessionId)) return
    started.current.add(sessionId)
    const cleanup = connectExecutionStream(sessionId, {
      onEvent: (event: ExecutionEvent) => dispatch({ type: 'event', sessionId, event }),
      onOpen: () => dispatch({ type: 'connection', sessionId, connection: 'connected' }),
      onReconnect: () => dispatch({ type: 'connection', sessionId, connection: 'reconnecting' }),
      onAuthProbe: () => { void getKeysStatus().catch(handleApiError) },
    })
    connections.current.set(sessionId, cleanup)
  }, [])

  const selectSession = useCallback((sessionId: string | null) => dispatch({ type: 'select', sessionId }), [])
  const resetSession = useCallback((sessionId: string) => dispatch({ type: 'reset', sessionId }), [])
  const toggleSession = useCallback((sessionId: string) => dispatch({ type: 'toggle', sessionId }), [])

  const selectedId = registry.selectedId
  const selectedState = useMemo<ExecutionState>(() => {
    if (!selectedId) return createInitialExecutionState()
    return registry.runtimes[selectedId]?.state ?? createInitialExecutionState()
  }, [registry.runtimes, selectedId])

  return {
    selectedId,
    selectedState,
    runtimes: registry.runtimes,
    startSession,
    selectSession,
    resetSession,
    toggleSession,
  }
}
