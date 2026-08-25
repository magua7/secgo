import { useCallback, useEffect, useReducer } from 'react'
import { executionReducer, initialExecutionState } from '../state/executionReducer'
import { getKeysStatus, handleApiError } from '../services/api'
import { connectExecutionStream } from '../services/sse'
import type { ExecutionEvent } from '../types/events'

export function useAgentExecution(sessionId: string | null) {
  const [state, dispatch] = useReducer(executionReducer, initialExecutionState)
  const reset = useCallback(() => dispatch({ type: 'ui:reset', data: {} }), [])
  const toggleExecution = useCallback(() => dispatch({ type: 'ui:toggle-execution', data: {} }), [])

  useEffect(() => {
    if (!sessionId) { reset(); return }
    return connectExecutionStream(sessionId, {
      onEvent: (event: ExecutionEvent) => dispatch(event),
      onOpen: () => dispatch({ type: 'ui:connection', data: { connection: 'connected' } }),
      onReconnect: () => dispatch({ type: 'ui:connection', data: { connection: 'reconnecting' } }),
      onAuthProbe: () => { void getKeysStatus().catch(handleApiError) },
    })
  }, [sessionId, reset])

  return { state, dispatch, reset, toggleExecution }
}
