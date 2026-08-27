import type { ExecutionTraceTab, ExecutionTraceViewModel } from '../../types/executionTrace'
import type { AgentId } from '../../types/execution'
import { AgentProgress } from '../execution/AgentProgress'
import { PanelEmptyState } from '../common/PanelEmptyState'
import { Icon } from '../common/Icon'

const DetailText = ({ detail }: { detail: string }) => {
  const short = detail.length > 180 ? `${detail.slice(0, 180)}…` : detail
  if (detail.length <= 180) return <p>{detail}</p>
  return <details className="history-raw-output"><summary>{short}</summary><pre className="history-trace-detail">{detail}</pre></details>
}

export function RightPanel({ view, tab, onTabChange, onCollapse }: { view: ExecutionTraceViewModel; tab: ExecutionTraceTab; onTabChange: (tab: ExecutionTraceTab) => void; onCollapse?: () => void }) {
  const direct = view.kind === 'direct_response'
  const empty = view.kind === 'empty'
  const snapshotHistory = view.mode === 'history'
  // 实际参与过的 Agent：只来自真实 timeline 事件，不按固定流水线猜
  const participatedAgents = [...new Set(view.timeline.map((item) => item.agent).filter((agent): agent is AgentId => Boolean(agent)))]
  return <aside className="right-panel">
    <div className={`right-head ${direct || empty ? 'neutral' : ''}`}>
      {empty
        ? <div className="right-context"><strong>尚未开始任务</strong><small>等待提交</small></div>
        : <>{direct
          ? <AgentProgress activeAgent={view.activeAgent} status="idle" participatedAgents={participatedAgents} />
          : <AgentProgress activeAgent={view.activeAgent} status={view.status} participatedAgents={participatedAgents} />}
          {snapshotHistory && <small className="history-badge">历史记录</small>}</>}
    </div>
    <div className="right-tabs-row">
      <div className="right-tabs" role="tablist">
        <button className={tab === 'trace' ? 'active' : ''} onClick={() => onTabChange('trace')}>执行轨迹</button>
        <button className={tab === 'evidence' ? 'active' : ''} onClick={() => onTabChange('evidence')}>关键证据</button>
        <button className={tab === 'decisions' ? 'active' : ''} onClick={() => onTabChange('decisions')}>决策记录</button>
      </div>
      <button type="button" className="right-panel-collapse-btn" onClick={onCollapse} aria-label="收起执行面板"><Icon name="chevron" /></button>
    </div>
    <div className="right-content">
      {empty ? <PanelEmptyState title="尚未开始任务" detail="提交安全任务后，这里将展示 Agent 执行轨迹、工具调用与阶段变化。" /> : direct ? <PanelEmptyState title="本轮为直接回复" detail="未触发 Agent 执行或工具调用。" /> : <>
        {tab === 'trace' && <div className="timeline">{view.timeline.length ? view.timeline.map((item) => <article key={item.id} className={item.at === null ? 'without-time' : ''}>{item.at !== null && <time>{new Date(item.at).toLocaleTimeString('zh-CN', { hour12: false })}</time>}<i className={item.status} /><div><strong>{item.title}</strong>{item.detail && <DetailText detail={item.detail} />}</div></article>) : <PanelEmptyState title="尚未开始执行" detail="任务开始后，这里会显示完整执行轨迹。" />}</div>}
        {tab === 'evidence' && <div className="evidence-list">{view.evidence.length ? view.evidence.map((item) => <article key={item.id ?? `${item.source}-${item.summary}`}><strong>{item.title ?? item.source}</strong><DetailText detail={item.summary} /></article>) : <PanelEmptyState title="暂无关键证据" detail="尚无通过证据 Gate 的有效发现（成功且有真实结果的工具输出）。" />}</div>}
        {tab === 'decisions' && <div className="decision-list">{view.decisions.length ? view.decisions.map((item) => {
          const selectedCandidate = item.candidates.find((c) => c.id === item.selected)
          return <article key={item.id} className="decision-card"><div className="decision-header"><strong className={`decision-trigger decision-trigger--${item.trigger}`}>{item.trigger}</strong><small>{item.timestamp ? new Date(item.timestamp * 1000).toLocaleTimeString('zh-CN', { hour12: false }) : ''}</small></div><p className="decision-detail">{item.trigger_detail}</p>{item.observation && <div className="decision-observe"><strong>当前观察：</strong><span>{item.observation}</span></div>}{selectedCandidate && <div className="decision-reason"><strong>最终选择：</strong><span>{selectedCandidate.description}</span></div>}<div className="decision-reason"><strong>选择理由：</strong><span>{item.reason}</span></div>{item.candidates.length > 0 && <details className="decision-candidates"><summary>候选策略（{item.candidates.length} 个）</summary>{item.candidates.map((c) => <div key={c.id} className={`decision-candidate ${c.id === item.selected ? 'selected' : 'rejected'}`}><span className="candidate-label">{c.id === item.selected ? '✅ 选中' : '❌ 放弃'}</span><strong>{c.description}</strong><small>风险: {c.risk} | 预期: {c.expected_outcome}</small></div>)}</details>}</article>
        }) : <PanelEmptyState title="暂无决策记录" detail="尚未产生需重规划的决策（连续失败/重复调用/无进展时自动触发）。" />}</div>}
      </>}
    </div>
  </aside>
}
