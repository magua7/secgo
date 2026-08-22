import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import type { Theme } from '../hooks/preferences'
import { useAgentExecution } from '../hooks/useAgentExecution'
import { usePanelPreferences } from '../hooks/preferences'
import { cancelSession, deleteSession, getSessionMessages, getSessions, handleApiError, renameSession, sendChat } from '../services/api'
import type { HistoryMessage, SessionSummary, TodoItem } from '../types/session'
import type { ExecutionTraceTab } from '../types/executionTrace'
import type { ConversationTurn } from '../types/conversation'
import { ConversationFeed } from '../components/conversation/ConversationFeed'
import { Composer } from '../components/conversation/Composer'
import { TasksDock } from '../components/execution/TasksDock'
import { Sidebar } from '../components/layout/Sidebar'
import { RightPanel } from '../components/layout/RightPanel'
import { Brand } from '../components/common/Brand'
import { Icon } from '../components/common/Icon'
import { ThemeToggle } from '../components/common/ThemeToggle'
import { historyMessagesToTrace, liveExecutionToTrace } from '../components/layout/executionTraceAdapter'
import { commitVisibleLiveTurn, liveExecutionToTurn } from '../components/conversation/conversationAdapter'
import { isNearBottom, shouldFollowStreamUpdate } from '../utils/autoFollow'
import { executionForTurnSubmission } from '../utils/turnSubmission'

interface Props { theme: Theme; onThemeToggle: () => void; onOpenSettings: () => void }

export function WorkspacePage({ theme, onThemeToggle, onOpenSettings }: Props) {
  const [sessionId, setSessionId] = useState<string | null>(() => sessionStorage.getItem('secgo.sessionId'))
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [messages, setMessages] = useState<HistoryMessage[]>([])
  const [historyTodoList, setHistoryTodoList] = useState<TodoItem[]>([])
  const [committedTurns, setCommittedTurns] = useState<ConversationTurn[]>([])
  const [question, setQuestion] = useState(() => sessionStorage.getItem('secgo.pendingQuestion') ?? '')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [rightTab, setRightTab] = useState<ExecutionTraceTab>('trace')
  const [showLatest, setShowLatest] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [turnFailed, setTurnFailed] = useState(false)
  const { leftMode, cycleLeft, rightVisible, setRightVisible } = usePanelPreferences()
  const { state, reset, toggleExecution } = useAgentExecution(sessionId)
  const feedRef = useRef<HTMLDivElement>(null)
  const autoFollowRef = useRef(true)
  const previousFinalTextRef = useRef('')
  const submissionStartedRef = useRef(false)
  const displayedExecution = executionForTurnSubmission(state, submitting ? 'pending' : turnFailed ? 'failed' : null)
  const running = submitting || state.status === 'running' || state.status === 'loading'
  const statusLabel = submitting ? '提交中' : turnFailed ? '发送失败' : displayedExecution.status === 'running' || displayedExecution.status === 'loading' ? '运行中' : displayedExecution.status === 'awaiting_input' ? '等待输入' : displayedExecution.status === 'completed' ? '已完成' : displayedExecution.status === 'cancelled' ? '已停止' : displayedExecution.status === 'error' ? '执行异常' : '就绪'
  const activeTitle = sessions.find((session) => session.id === sessionId)?.title || (question ? question.slice(0, 48) : '新建任务')
  const showTaskStatus = Boolean(sessionId || question || state.status !== 'idle')
  const liveTurn = useMemo(() => liveExecutionToTurn(question, displayedExecution), [question, displayedExecution])
  const liveTrace = useMemo(() => liveExecutionToTrace(displayedExecution), [displayedExecution])
  const historyTrace = useMemo(() => historyMessagesToTrace(messages, historyTodoList), [messages, historyTodoList])
  const rightTrace = question ? liveTrace : historyTrace
  const workspaceColumns = { '--workspace-left': leftMode === 'expanded' ? '250px' : '0px', '--workspace-right': rightVisible ? '340px' : '0px' } as CSSProperties

  const loadSessions = async () => { try { setSessions((await getSessions()).sessions) } catch (reason) { setError(handleApiError(reason)) } }
  useEffect(() => { void loadSessions() }, [])
  useEffect(() => { sessionStorage.removeItem('secgo.pendingQuestion') }, [])
  useEffect(() => { if (state.status === 'completed' || state.status === 'cancelled' || state.status === 'error') void loadSessions() }, [state.status])
  useEffect(() => {
    if (submitting && state.status === 'running') {
      submissionStartedRef.current = true
      setSubmitting(false)
      setTurnFailed(false)
    }
  }, [state.status, submitting])
  useEffect(() => {
    const text = liveTurn.finalAnswer ?? ''
    if (!liveTurn.isFinalStreaming || text === previousFinalTextRef.current) {
      previousFinalTextRef.current = text
      return
    }
    const feed = feedRef.current
    if (feed && shouldFollowStreamUpdate(autoFollowRef.current)) {
      feed.scrollTo({ top: feed.scrollHeight })
      setShowLatest(false)
    } else if (feed) setShowLatest(true)
    previousFinalTextRef.current = text
  }, [liveTurn.finalAnswer, liveTurn.isFinalStreaming])
  useEffect(() => {
    const feed = feedRef.current
    if (feed && !autoFollowRef.current && (state.timeline.length || state.keyProgress.length)) setShowLatest(true)
  }, [state.timeline.length, state.keyProgress.length, state.currentActivity])

  const select = async (id: string) => {
    setLoading(true); setError(''); reset(); setQuestion(''); setCommittedTurns([]); setSessionId(id); sessionStorage.setItem('secgo.sessionId', id)
    try {
      const result = await getSessionMessages(id)
      setMessages(result.messages); setHistoryTodoList(result.todoList)
      requestAnimationFrame(() => feedRef.current?.scrollTo({ top: 0 }))
    }
    catch (reason) { setError(handleApiError(reason)) } finally { setLoading(false) }
  }
  const create = () => { reset(); setSessionId(null); setMessages([]); setHistoryTodoList([]); setCommittedTurns([]); setQuestion(''); sessionStorage.removeItem('secgo.sessionId') }
  const send = async (text: string, attachmentIds: string[]) => {
    const questionText = text || '请分析这些附件。'
    setCommittedTurns((turns) => commitVisibleLiveTurn(turns, question, displayedExecution))
    submissionStartedRef.current = false; setSubmitting(true); setTurnFailed(false); setQuestion(questionText); setError(''); autoFollowRef.current = true; setShowLatest(false)
    requestAnimationFrame(() => { const feed = feedRef.current; if (feed) feed.scrollTo({ top: feed.scrollHeight }) })
    try {
      const result = await sendChat(text, sessionId ?? undefined, attachmentIds)
      if (!sessionId) { setSessionId(result.sessionId); sessionStorage.setItem('secgo.sessionId', result.sessionId) }
      await loadSessions()
    } catch (reason) {
      if (!submissionStartedRef.current) { setSubmitting(false); setTurnFailed(true) }
      setError(handleApiError(reason))
      throw reason
    }
  }
  const stop = async () => { if (sessionId) try { await cancelSession(sessionId) } catch (reason) { setError(handleApiError(reason)) } }
  const rename = async (session: SessionSummary) => { const title = window.prompt('会话新标题：', session.title); if (title?.trim()) { await renameSession(session.id, title.trim()); await loadSessions() } }
  const remove = async (session: SessionSummary) => { if (!window.confirm('删除该会话？此操作不可恢复。')) return; await deleteSession(session.id); if (session.id === sessionId) create(); await loadSessions() }
  const onFeedScroll = () => {
    const feed = feedRef.current
    if (!feed) return
    const nearBottom = isNearBottom(feed)
    autoFollowRef.current = nearBottom
    if (nearBottom) setShowLatest(false)
  }
  const returnToLatest = () => {
    const feed = feedRef.current
    if (!feed) return
    autoFollowRef.current = true; setShowLatest(false); feed.scrollTo({ top: feed.scrollHeight })
  }
  const toggleRightPanel = () => setRightVisible(!rightVisible)

  return <div className="workspace-page" style={workspaceColumns}>
    <header className="workspace-top"><div className="workspace-brand"><button onClick={() => { window.location.hash = '#/' }}><Brand /></button></div><div className="workspace-task-title">{showTaskStatus && <span>{statusLabel}</span>}<strong>{activeTitle}</strong></div><div className="workspace-actions"><span className="connection"><i className={state.connection} />{state.connection === 'reconnecting' ? '重连中' : '在线'}</span><ThemeToggle theme={theme} onToggle={onThemeToggle} /><span className="user-label"><Icon name="user" />用户</span><button className="icon-button" onClick={onOpenSettings} aria-label="打开设置"><Icon name="settings" /></button></div></header>
    <div className="workspace-body">
      <div className={`panel-shell left-panel-shell ${leftMode}`}><Sidebar mode={leftMode} sessions={sessions} currentId={sessionId} onCycle={cycleLeft} onNew={create} onSelect={(id) => void select(id)} onRename={(session) => void rename(session)} onDelete={(session) => void remove(session)} onSettings={onOpenSettings} /><button className="panel-edge-handle left" onClick={cycleLeft} aria-label={leftMode === 'hidden' ? '展开历史侧栏' : '折叠历史侧栏'}>{leftMode === 'hidden' ? '›' : '‹'}</button></div>
      <main className="workspace-center">
      <div className="workspace-scroll" ref={feedRef} onScroll={onFeedScroll}>{loading ? <div className="loading-state">正在加载会话…</div> : <ConversationFeed messages={messages} todoList={historyTodoList} committedTurns={committedTurns} currentQuestion={question} execution={displayedExecution} onToggleExecution={toggleExecution} />}{error && <div className="workspace-error">{error}</div>}</div>
      {showLatest && <button className="return-latest" onClick={returnToLatest}>↓ 回到最新</button>}
      <div className="workspace-input"><TasksDock tasks={displayedExecution.tasks} status={displayedExecution.status} /><Composer running={running} onSend={send} onStop={stop} /></div>
      </main>
      <div className={`panel-shell right-panel-shell ${rightVisible ? 'visible' : 'hidden'}`}><button className="panel-edge-handle right" onClick={toggleRightPanel} aria-label={rightVisible ? '折叠执行面板' : '展开执行面板'}>{rightVisible ? '›' : '‹'}</button>{rightVisible && <RightPanel view={rightTrace} tab={rightTab} onTabChange={setRightTab} />}</div>
    </div>
  </div>
}
