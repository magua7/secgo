import type { ExecutionTraceTab, ExecutionTraceViewModel } from '../../types/executionTrace'
import { AgentProgress } from '../execution/AgentProgress'
import { PanelEmptyState } from '../common/PanelEmptyState'

export function RightPanel({ view, tab, onTabChange }: { view: ExecutionTraceViewModel; tab: ExecutionTraceTab; onTabChange: (tab: ExecutionTraceTab) => void }) {
  const direct = view.kind === 'direct_response'
  const empty = view.kind === 'empty'
  const historical = view.mode === 'history-readonly'
  return <aside className="right-panel">
    <div className={`right-head ${historical || direct || empty ? 'neutral' : ''}`}>
      {empty
        ? <div className="right-context"><strong>尚未开始任务</strong><small>等待提交</small></div>
        : historical
        ? <div className="right-context"><strong>历史执行回放</strong><small>只读</small></div>
        : direct
          ? <AgentProgress activeAgent={view.activeAgent} status="idle" />
          : <AgentProgress activeAgent={view.activeAgent} status={view.status} />}
    </div>
    <div className="right-tabs" role="tablist">
      <button className={tab === 'trace' ? 'active' : ''} onClick={() => onTabChange('trace')}>执行轨迹</button>
      <button className={tab === 'evidence' ? 'active' : ''} onClick={() => onTabChange('evidence')}>证据</button>
      <button className={tab === 'resources' ? 'active' : ''} onClick={() => onTabChange('resources')}>资源</button>
    </div>
    <div className="right-content">
      {empty ? <PanelEmptyState title="尚未开始任务" detail="提交安全任务后，这里将展示 Agent 执行轨迹、工具调用与阶段变化。" /> : direct ? <PanelEmptyState title="本轮为直接回复" detail="未触发 Agent 执行或工具调用。" /> : <>
        {view.notice && <p className="history-trace-notice">{view.notice}</p>}
        {tab === 'trace' && <div className={`timeline ${historical ? 'history-timeline' : ''}`}>{view.timeline.length ? view.timeline.map((item) => <article key={item.id} className={item.at === null ? 'without-time' : ''}>{item.at !== null && <time>{new Date(item.at).toLocaleTimeString('zh-CN', { hour12: false })}</time>}<i className={item.status} /><div><strong>{item.title}</strong>{item.detail && (historical ? <><p>{item.kind === 'tool' ? '执行完成' : item.kind === 'handoff' ? '已恢复内部交接记录' : '已恢复历史文本'}</p><details className="history-raw-output"><summary>{item.kind === 'tool' ? '查看原始输出' : '查看内容'}</summary><pre className="history-trace-detail">{item.detail}</pre></details></> : <p>{item.detail}</p>)}</div></article>) : <PanelEmptyState title={historical ? '暂无可回放轨迹' : '尚未开始执行'} detail={historical ? '本轮历史未保存完整执行轨迹。' : '任务开始后，这里会显示完整执行轨迹。'} />}</div>}
        {tab === 'evidence' && <div className="evidence-list">{view.evidence.length ? view.evidence.map((item, index) => <article key={`${item.source}-${index}`}><strong>{item.source}</strong><p>{item.summary}</p></article>) : <PanelEmptyState title="暂无证据" detail={historical ? '本轮历史未保存可恢复的证据记录。' : '尚未形成可展示的证据。'} />}</div>}
        {tab === 'resources' && <div className="resource-list">{view.resources.length ? view.resources.map((tool, index) => <article key={`${tool.name}-${index}`}><i className={tool.status} /><div><strong>{tool.name}</strong><small>{tool.status === 'running' ? '调用中' : '本次任务已使用'}</small></div></article>) : <PanelEmptyState title="暂无资源记录" detail={historical ? '本轮历史未保存可恢复的资源记录。' : '本次任务尚未调用工具或资源。'} />}</div>}
      </>}
    </div>
  </aside>
}
