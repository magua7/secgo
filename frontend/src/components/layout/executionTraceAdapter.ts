import type { ExecutionState, ToolUse } from '../../types/execution'
import type { ExecutionTraceViewModel, ResourceGroup } from '../../types/executionTrace'
import type { RunSnapshot } from '../../types/snapshot'
import { hasAgentTaskSignals, snapshotToExecutionState } from '../conversation/conversationAdapter'

export function aggregateResources(tools: ToolUse[]): ResourceGroup[] {
  const groups = new Map<string, ToolUse[]>()
  tools.forEach((tool) => groups.set(tool.name, [...(groups.get(tool.name) ?? []), tool]))
  return [...groups].map(([name, invocations]) => ({ name, count: invocations.length, invocations }))
}

export function liveExecutionToTrace(state: ExecutionState): ExecutionTraceViewModel {
  const task = hasAgentTaskSignals(state)
  return {
    mode: 'live',
    kind: task ? 'agent_task' : 'direct_response',
    status: state.status,
    activeAgent: state.activeAgent,
    timeline: task ? state.timeline : [],
    evidence: task ? state.evidence : [],
    resources: task ? aggregateResources(state.tools) : [],
    notice: null,
  }
}

// 历史 RunSnapshot → 与实时相同的 ExecutionTraceViewModel（同一套 RightPanel 渲染）。
export function executionSnapshotToTraceView(snapshot: RunSnapshot): ExecutionTraceViewModel {
  const trace = liveExecutionToTrace(snapshotToExecutionState(snapshot))
  return { ...trace, mode: 'history' }
}
