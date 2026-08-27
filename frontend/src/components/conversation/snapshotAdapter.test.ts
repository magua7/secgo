import { describe, expect, it } from 'vitest'
import type { RunSnapshot } from '../../types/snapshot'
import type { PersistedTurn } from '../../types/session'
import { persistedTurnToConversationTurn, snapshotToExecutionState } from './conversationAdapter'
import { aggregateResources, executionSnapshotToTraceView } from '../layout/executionTraceAdapter'

const snapshot: RunSnapshot = {
  run_id: 'r1', session_id: 's1', turn_id: 't1',
  status: 'completed', phase: 'completed', reason: 'completed', error: null,
  active_agent: 'builder', started_at: 1000, ended_at: 3000,
  current_activity: '研判完成',
  narrative_updates: [{ id: 'n1', text: '已完成基础指纹识别。', agent: 'operator', timestamp: 1500 }],
  key_progress: ['已匹配当前任务所需安全能力'],
  key_findings: ['发现 /admin 等入口'],
  tasks: [{ text: '侦察', done: true }, { text: '报告', done: false }],
  timeline: [{ id: 't1', at: 1100, kind: 'agent', agent: 'planner', title: 'planner 正在执行', status: 'running' }],
  evidence: [{ id: 'e1', type: 'finding', title: '网页搜索结果', source: 'web_search', summary: 'found', timestamp: 2000 }],
  resources: [
    { name: 'execute_bash', status: 'completed', result: 'r1', at: 1200 },
    { name: 'execute_bash', status: 'completed', result: 'r2', at: 1300 },
    { name: 'skill_list', status: 'completed', result: 'r3', at: 1400 },
  ],
  final_report: '# 最终报告', partial_report: null, last_assistant_output: '# 最终报告',
  tool_count: 3, evidence_count: 1, total_steps: 4,
}

describe('snapshotToExecutionState', () => {
  it('sanitizes legacy snapshots containing the internal task_complete todo row', () => {
    const dirty = snapshotToExecutionState({
      ...snapshot,
      current_activity: 'planner 正在调用 task_complete',
      tasks: [
        { text: '技能路由与技能读取（ctf-solve-mode）', done: true },
        { text: '最终汇报并 task_complete', done: false },
      ],
    })
    expect(dirty.tasks.map((task) => task.text)).toEqual(['技能路由与技能读取（ctf-solve-mode）'])
    expect(dirty.completedSteps).toEqual(['技能路由与技能读取（ctf-solve-mode）'])
    expect(dirty.currentActivity).not.toContain('task_complete')
  })

  it('hydrates terminal status/phase and preserves timeline/evidence/resources', () => {
    const state = snapshotToExecutionState(snapshot)
    expect(state.status).toBe('completed')
    expect(state.phase).toBe('completed')
    expect(state.finalAnswer).toBe('# 最终报告')
    expect(state.timeline).toHaveLength(1)
    expect(state.evidence).toHaveLength(1)
    expect(state.tools).toHaveLength(3)
    expect(state.startedAt).toBe(1000)
    expect(state.endedAt).toBe(3000)
    expect(state.completedSteps).toEqual(['侦察'])
  })

  it('maps stopped snapshot to cancelled execution status', () => {
    const state = snapshotToExecutionState({ ...snapshot, status: 'stopped', phase: 'stopped', final_report: null, partial_report: '# 部分结果' })
    expect(state.status).toBe('cancelled')
    expect(state.phase).toBe('stopped')
    expect(state.finalAnswer).toBe('# 部分结果')
    expect(state.executionExpanded).toBe(true)
  })
})

describe('persistedTurnToConversationTurn', () => {
  it('maps an agent-task turn with structured attachments and final report', () => {
    const turn: PersistedTurn = {
      id: 't1', sequence: 1, kind: 'agent_task',
      userMessage: { text: '这是一个杂项题，你能找到flag吗', attachments: [{ id: 'a1', filename: '雪中刀盾.zip', mimeType: 'application/zip', kind: 'binary', size: 2100000 }] },
      assistantAnswer: '# 最终报告', execution: snapshot, status: 'completed',
      createdAt: null, updatedAt: null,
    }
    const mapped = persistedTurnToConversationTurn(turn)
    expect(mapped.id).toBe('t1')
    expect(mapped.userMessage.text).toBe('这是一个杂项题，你能找到flag吗')
    expect(mapped.userMessage.attachments?.[0]?.filename).toBe('雪中刀盾.zip')
    expect(mapped.finalAnswer).toBe('# 最终报告')
    expect(mapped.execution).not.toBeNull()
  })

  it('maps a plain direct-response turn as a formal turn (not dropped)', () => {
    const turn: PersistedTurn = {
      id: 't2', sequence: 1, kind: 'direct_response',
      userMessage: { text: '你好', attachments: [] },
      assistantAnswer: '你好，我是 SEC-GO。', execution: null, status: 'awaiting_user',
      createdAt: null, updatedAt: null,
    }
    const mapped = persistedTurnToConversationTurn(turn)
    expect(mapped.kind).toBe('direct_response')
    expect(mapped.userMessage.text).toBe('你好')
    expect(mapped.finalAnswer).toBe('你好，我是 SEC-GO。')
    expect(mapped.execution).toBeNull()
  })
})

describe('aggregateResources', () => {
  it('groups repeated tools by name with counts (TEST 8)', () => {
    const state = snapshotToExecutionState(snapshot)
    const groups = aggregateResources(state.tools)
    const bash = groups.find((group) => group.name === 'execute_bash')
    expect(bash?.count).toBe(2)
    expect(groups.map((group) => `${group.name}:${group.count}`)).toEqual(['execute_bash:2', 'skill_list:1'])
  })
})

describe('executionSnapshotToTraceView', () => {
  it('produces the same live trace view shape from a snapshot', () => {
    const view = executionSnapshotToTraceView(snapshot)
    expect(view.mode).toBe('history')
    expect(view.status).toBe('completed')
    expect(view.timeline).toHaveLength(1)
    expect(view.evidence).toHaveLength(1)
    expect(view.resources.find((group) => group.name === 'execute_bash')?.count).toBe(2)
  })
})
