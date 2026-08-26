import type { ExecutionTraceTab, ExecutionTraceViewModel } from '../../types/executionTrace'
import { AgentProgress } from '../execution/AgentProgress'
import { PanelEmptyState } from '../common/PanelEmptyState'

const DetailText = ({ detail }: { detail: string }) => {
  const short = detail.length > 180 ? `${detail.slice(0, 180)}…` : detail
  if (detail.length <= 180) return <p>{detail}</p>
  return <details className="history-raw-output"><summary>{short}</summary><pre className="history-trace-detail">{detail}</pre></details>
}

export function RightPanel({ view, tab, onTabChange }: { view: ExecutionTraceViewModel; tab: ExecutionTraceTab; onTabChange: (tab: ExecutionTraceTab) => void }) {
  const direct = view.kind === 'direct_response'
  const empty = view.kind === 'empty'
  const snapshotHistory = view.mode === 'history'
  return <aside className="right-panel">
    <div className={`right-head ${direct || empty ? 'neutral' : ''}`}>
      {empty
        ? <div className="right-context"><strong>尚未开始任务</strong><small>等待提交</small></div>
        : <>{direct
          ? <AgentProgress activeAgent={view.activeAgent} status="idle" />
          : <AgentProgress activeAgent={view.activeAgent} status={view.status} />}
          {snapshotHistory && <small className="history-badge">历史记录</small>}</>}
    </div>
    <div className="right-tabs" role="tablist">
      <button className={tab === 'trace' ? 'active' : ''} onClick={() => onTabChange('trace')}>执行轨迹</button>
      <button className={tab === 'evidence' ? 'active' : ''} onClick={() => onTabChange('evidence')}>证据</button>
      <button className={tab === 'resources' ? 'active' : ''} onClick={() => onTabChange('resources')}>资源</button>
    </div>
    <div className="right-content">
      {empty ? <PanelEmptyState title="尚未开始任务" detail="提交安全任务后，这里将展示 Agent 执行轨迹、工具调用与阶段变化。" /> : direct ? <PanelEmptyState title="本轮为直接回复" detail="未触发 Agent 执行或工具调用。" /> : <>
        {tab === 'trace' && <div className="timeline">{view.timeline.length ? view.timeline.map((item) => <article key={item.id} className={item.at === null ? 'without-time' : ''}>{item.at !== null && <time>{new Date(item.at).toLocaleTimeString('zh-CN', { hour12: false })}</time>}<i className={item.status} /><div><strong>{item.title}</strong>{item.detail && <DetailText detail={item.detail} />}</div></article>) : <PanelEmptyState title="尚未开始执行" detail="任务开始后，这里会显示完整执行轨迹。" />}</div>}
        {tab === 'evidence' && <div className="evidence-list">{view.evidence.length ? view.evidence.map((item) => <article key={item.id ?? `${item.source}-${item.summary}`}><strong>{item.title ?? item.source}</strong><DetailText detail={item.summary} /></article>) : <PanelEmptyState title="暂无证据" detail="尚未形成可展示的证据。" />}</div>}
        {tab === 'resources' && <div className="resource-list">{view.resources.length ? view.resources.map((group) => <details key={group.name} className="resource-group"><summary><strong>{group.name}</strong><small>× {group.count}</small></summary>{group.invocations.map((invocation, index) => <div className="resource-invocation" key={`${group.name}-${index}`}><i className={invocation.status} /><span>第 {index + 1} 次调用</span>{invocation.result && <details className="history-raw-output"><summary>查看输出</summary><pre className="history-trace-detail">{invocation.result}</pre></details>}</div>)}</details>) : <PanelEmptyState title="暂无资源记录" detail="本次任务尚未调用工具或资源。" />}</div>}
      </>}
    </div>
  </aside>
}
