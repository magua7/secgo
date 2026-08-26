import type { AgentId, ConversationPhase, ExecutionStatus } from '../../types/execution'

interface Props {
  status: ExecutionStatus
  phase: ConversationPhase
  activeAgent: AgentId
  currentActivity: string
  elapsedMs: number | null
  toolCount: number
  evidenceCount: number
}

const agentAction: Record<string, string> = {
  planner: '正在规划',
  research: '正在检索',
  operator: '正在验证',
  builder: '正在构建',
}

const formatElapsed = (ms: number | null): string => {
  if (ms === null || ms < 0) return ''
  const total = Math.floor(ms / 1000)
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
}

const fallbackActivity = (phase: ConversationPhase, agent: AgentId): string => {
  if (phase === 'planning') return '正在分析任务目标'
  if (phase === 'reporting') return '正在整理证据并生成研判报告'
  if (phase === 'awaiting_user') return '需要更多任务信息'
  if (phase === 'executing') return `${agentAction[agent] ?? '正在执行'}当前阶段任务`
  return '正在执行'
}

// 底部轻量、持久的 Agent Task 状态条：状态 · Agent · 当前活动 · 运行时间。
// 不承担关键进展 / 证据 / 轨迹 / 控制按钮（这些由 ExecutionBlock、RightPanel、Composer 承担）。
export function TaskStatusBar({ status, phase, activeAgent, currentActivity, elapsedMs, toolCount, evidenceCount }: Props) {
  const terminal = status === 'completed' || status === 'cancelled' || status === 'error'
  const mark = status === 'completed' ? '✓' : status === 'cancelled' ? '■' : status === 'error' ? '⚠' : '●'
  const elapsed = formatElapsed(elapsedMs)

  if (terminal) {
    const label = status === 'completed' ? '研判完成' : status === 'cancelled' ? '任务已停止' : '执行失败'
    return <div className={`task-status-bar terminal ${status}`}>
      <span className="tsb-mark"><i>{mark}</i></span>
      <span className="tsb-label">{label}</span>
      <span className="tsb-stats">{toolCount} Tools · {evidenceCount} Evidence</span>
      <span className="tsb-elapsed">{elapsed}</span>
    </div>
  }

  const label = phase === 'reporting'
    ? '正在生成报告'
    : phase === 'planning'
      ? '正在规划'
      : phase === 'awaiting_user'
        ? '等待补充'
        : (agentAction[activeAgent] ?? '正在执行')
  const activity = currentActivity || fallbackActivity(phase, activeAgent) || (agentAction[activeAgent] ?? '正在执行')
  return <div className="task-status-bar">
    <span className="tsb-status">{mark} {label}</span>
    <span className="tsb-agent">{activeAgent}</span>
    <span className="tsb-activity" title={activity}>{activity}</span>
    <span className="tsb-elapsed">{elapsed}</span>
  </div>
}
