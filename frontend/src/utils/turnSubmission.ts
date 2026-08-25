import { initialExecutionState } from '../state/executionReducer'
import type { ExecutionState } from '../types/execution'

export type TurnSubmissionMode = 'pending' | 'failed' | null

export function executionForTurnSubmission(state: ExecutionState, mode: TurnSubmissionMode): ExecutionState {
  if (mode === null) return state
  return {
    ...initialExecutionState,
    status: mode === 'pending' ? 'loading' : 'idle',
    phase: mode === 'pending' ? 'planning' : 'idle',
    currentActivity: mode === 'pending' ? '正在提交新消息' : '',
    connection: state.connection,
  }
}
