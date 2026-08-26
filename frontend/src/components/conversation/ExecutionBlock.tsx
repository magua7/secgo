import Markdown from 'react-markdown'
import type { ExecutionState } from '../../types/execution'
import type { ExecutionPresentation } from '../../types/conversation'
import { useElapsedTime } from '../../hooks/useElapsedTime'
import { Icon } from '../common/Icon'
import { executionToPresentation } from './conversationAdapter'

const agentLabels: Record<string, string> = { planner: '规划', research: '检索', operator: '验证', builder: '报告', agent: '历史执行' }

const formatElapsed = (elapsedMs: number | null) => {
  if (elapsedMs === null) return ''
  const seconds = Math.max(0, Math.floor(elapsedMs / 1000))
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
}

export function ExecutionBlock({ state, presentation, onToggle = () => undefined }: { state?: ExecutionState; presentation?: ExecutionPresentation; onToggle?: () => void }) {
  const view = presentation ?? (state ? executionToPresentation(state) : null)
  const liveElapsed = useElapsedTime(view?.startedAt ?? null, view?.endedAt ?? null, view?.status === 'running' || view?.status === 'loading')
  if (!view) return null
  const toolCount = view.toolGroups.reduce((sum, group) => sum + group.count, 0)
  const completed = view.status === 'completed' || view.phase === 'completed'
  const stopped = view.status === 'cancelled' || view.phase === 'stopped'
  const failed = view.status === 'error' || view.phase === 'error'
  const reporting = view.phase === 'reporting'
  const elapsed = formatElapsed(liveElapsed ?? view.elapsedMs)
  const terminalLabel = completed
    ? '研判完成'
    : reporting
      ? '正在生成报告'
      : stopped
        ? '任务已停止'
        : failed
          ? '执行失败'
          : view.phase === 'planning'
            ? '正在规划安全研判'
            : view.phase === 'awaiting_user' || view.status === 'awaiting_input'
              ? '等待你的补充输入'
              : view.source === 'history'
                ? '历史执行记录'
                : '正在执行安全研判'
  const expandedLabel = completed
    ? '研判完成'
    : reporting
      ? '正在生成报告'
      : stopped
        ? '任务已停止'
        : failed
          ? '执行失败'
          : view.phase === 'planning'
            ? '正在规划安全研判'
            : view.phase === 'awaiting_user'
              ? '等待你的补充输入'
              : '正在执行安全研判'
  const historicalNarration = view.source === 'history' ? view.details.filter((item) => item.kind === 'narrative').slice(-4) : []
  const currentActivity = view.currentActivity || (historicalNarration.length > 0
    ? '已恢复可读取的历史 Agent 执行记录'
    : view.phase === 'planning'
    ? 'Planner 正在规划当前安全研判的执行路径'
    : view.phase === 'executing'
      ? `${agentLabels[view.activeAgent] ?? view.activeAgent} 正在执行当前阶段任务`
      : view.phase === 'awaiting_user'
        ? '等待你的补充输入后继续执行'
        : reporting
          ? 'Builder 正在生成最终研判报告'
          : stopped
            ? '本次执行已由用户停止'
            : failed
              ? '本次执行发生异常'
              : '')
  const recentNarration = view.narrativeUpdates.slice(-4)
  if (!view.expanded) return <section className="execution-block execution-thin">
    <span className={`status-mark ${completed || reporting ? 'success' : view.status}`}><Icon name={completed || reporting ? 'check' : 'stop'} /></span>
    <strong>{terminalLabel}</strong>
    <span>{elapsed && `· ${elapsed} `}· {view.completedTasks}/{view.totalTasks} 任务 · {toolCount} Tools{view.evidenceCount !== null && ` · ${view.evidenceCount} Evidence`}</span>
    <button onClick={onToggle}>展开 <Icon name="chevron" /></button>
  </section>
  return <section className="execution-block">
    <button className="execution-head" onClick={onToggle} aria-expanded="true">
      <span><i className={`pulse ${view.status}`} />{expandedLabel}{elapsed && ` · ${elapsed}`}</span>
      <span>收起</span>
    </button>
    <div className="execution-body">
      <div className="execution-summary">
        {currentActivity && <section className="current-activity"><h3>{completed || stopped || failed ? '最后活动' : '当前活动'}</h3><div className="execution-agent"><strong>{agentLabels[view.activeAgent] ?? view.activeAgent}</strong><small>{view.activeAgent}</small></div><p>● {currentActivity}</p></section>}
        {recentNarration.length > 0 && <section className="live-narration"><h3>过程播报</h3>{recentNarration.map((item) => <div className="narrative-line" key={item.id}><time dateTime={new Date(item.timestamp).toISOString()}>{new Date(item.timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}</time><div><Markdown>{item.text}</Markdown></div></div>)}</section>}
        {recentNarration.length === 0 && historicalNarration.length > 0 && <section className="live-narration"><h3>过程播报</h3>{historicalNarration.map((item) => <div className="narrative-line" key={item.id}><span>历史</span><div><Markdown>{item.text}</Markdown></div></div>)}</section>}
        {view.keyProgress.length > 0 && <section><h3>关键进展</h3>{view.keyProgress.slice(-8).map((item) => <div className="progress-line" key={item}><span>✓</span><Markdown>{item}</Markdown></div>)}</section>}
      </div>
      <div className="execution-foot"><div className="execution-stats"><span>{view.completedTasks}/{view.totalTasks} 任务</span><span>{toolCount} 工具</span>{view.evidenceCount !== null && <span>{view.evidenceCount} 证据</span>}</div></div>
      {view.error && <p className="inline-error">{view.error}</p>}
    </div>
  </section>
}
