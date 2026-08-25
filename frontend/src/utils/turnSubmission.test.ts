import { describe, expect, it } from 'vitest'
import { initialExecutionState } from '../state/executionReducer'
import { executionForTurnSubmission } from './turnSubmission'

describe('turn submission presentation', () => {
  it('does not attach the previous completed execution to a newly submitted question', () => {
    const previous = {
      ...initialExecutionState,
      status: 'completed' as const,
      phase: 'completed' as const,
      tasks: [{ text: '上一轮任务', done: true }],
      finalAnswer: '上一轮结论',
    }
    const pending = executionForTurnSubmission(previous, 'pending')
    const failed = executionForTurnSubmission(previous, 'failed')
    expect(pending.status).toBe('loading')
    expect(pending.tasks).toHaveLength(0)
    expect(pending.finalAnswer).toBe('')
    expect(failed.status).toBe('idle')
    expect(failed.tasks).toHaveLength(0)
  })
})
