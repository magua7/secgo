import { describe, expect, it } from 'vitest'
import { aggregateResources, executionSnapshotToTraceView, liveExecutionToTrace } from './executionTraceAdapter'
import { initialExecutionState } from '../../state/executionReducer'
import type { RunSnapshot } from '../../types/snapshot'

describe('execution trace adapters', () => {
  it('aggregates repeated tools into one resource group per name', () => {
    const groups = aggregateResources([
      { name: 'execute_bash', status: 'completed', result: 'r1' },
      { name: 'execute_bash', status: 'completed', result: 'r2' },
      { name: 'skill_list', status: 'completed', result: 'r3' },
    ])
    expect(groups.map((group) => `${group.name}:${group.count}`)).toEqual(['execute_bash:2', 'skill_list:1'])
  })

  it('builds a live trace with aggregated resources and empty evidence', () => {
    const view = liveExecutionToTrace({
      ...initialExecutionState,
      status: 'running',
      tasks: [{ text: '侦察', done: false }],
      tools: [{ name: 'port_scan', status: 'completed', result: '443 open' }],
    })
    expect(view.mode).toBe('live')
    expect(view.kind).toBe('agent_task')
    expect(view.resources[0]).toMatchObject({ name: 'port_scan', count: 1 })
    expect(view.evidence).toHaveLength(0)
  })

  it('produces a history trace view from a snapshot with the same shape', () => {
    const snapshot: RunSnapshot = {
      run_id: 'r1', session_id: 's1', turn_id: 1,
      status: 'completed', phase: 'completed', reason: 'completed', error: null,
      active_agent: 'builder', started_at: 1000, ended_at: 2000, current_activity: '研判完成',
      narrative_updates: [], key_progress: [], key_findings: [], tasks: [],
      timeline: [{ id: 't1', at: 1100, kind: 'agent', agent: 'planner', title: 'planner 正在执行', status: 'running' }],
      evidence: [], resources: [{ name: 'skill_list', status: 'completed', result: 'r', at: 1200 }],
      final_report: '# 报告', partial_report: null, last_assistant_output: '# 报告',
      tool_count: 1, evidence_count: 0, total_steps: 2,
    }
    const view = executionSnapshotToTraceView(snapshot)
    expect(view.mode).toBe('history')
    expect(view.status).toBe('completed')
    expect(view.timeline).toHaveLength(1)
    expect(view.resources[0]).toMatchObject({ name: 'skill_list', count: 1 })
  })
})
