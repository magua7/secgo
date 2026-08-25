import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ConversationTurn } from '../../types/conversation'
import { TurnView } from './TurnView'

describe('TurnView execution expansion', () => {
  it('expands a collapsed execution summary without showing a duplicate trace link', () => {
    const turn: ConversationTurn = {
      id: 'committed-turn-1', kind: 'agent_task', phase: 'completed', userMessage: { text: '检查 example.com' }, finalAnswer: '完成', isFinalStreaming: false,
      execution: {
        source: 'live', status: 'completed', phase: 'completed', activeAgent: 'planner', currentActivity: '研判完成', keyProgress: [], narrativeUpdates: [], details: [], toolGroups: [],
        completedTasks: 1, totalTasks: 1, evidenceCount: 0, totalSteps: 1, agentCount: 1, error: null, expanded: false, elapsedMs: 1000,
        startedAt: 0, endedAt: 1000,
      },
    }
    render(<TurnView turn={turn} />)
    fireEvent.click(screen.getByText(/展开/))
    expect(screen.getByText(/收起/)).toBeInTheDocument()
    expect(screen.queryByText(/查看执行轨迹/)).not.toBeInTheDocument()
  })
})
