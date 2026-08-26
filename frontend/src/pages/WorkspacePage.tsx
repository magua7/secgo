import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useExecutionRegistry } from '../hooks/useExecutionRegistry'
import { useElapsedTime } from '../hooks/useElapsedTime'
import { cancelSession, deleteSession, getSessionMessages, getSessions, handleApiError, renameSession, sendChat } from '../services/api'
import type { SessionSummary, PersistedTurn } from '../types/session'
import type { ExecutionTraceTab } from '../types/executionTrace'
import type { ConversationTurn } from '../types/conversation'
import type { ExecutionState } from '../types/execution'
import type { MessageAttachment } from '../types/attachment'
import { ConversationFeed } from '../components/conversation/ConversationFeed'
import { Composer } from '../components/conversation/Composer'
import { TasksDock } from '../components/execution/TasksDock'
import { TaskStatusBar } from '../components/execution/TaskStatusBar'
import { Sidebar } from '../components/layout/Sidebar'
import { RightPanel } from '../components/layout/RightPanel'
import { Icon } from '../components/common/Icon'
import { executionSnapshotToTraceView, liveExecutionToTrace } from '../components/layout/executionTraceAdapter'
import { hasAgentTaskSignals, liveExecutionToTurn, persistedTurnsToConversationTurns, selectTaskExecution } from '../components/conversation/conversationAdapter'
import { isNearBottom, shouldFollowStreamUpdate } from '../utils/autoFollow'
import { executionForTurnSubmission } from '../utils/turnSubmission'

const activeStatuses = new Set(['queued', 'running', 'awaiting_user'])

interface WorkspacePageProps {
  rightVisible: boolean
  setRightVisible: (visible: boolean) => void
}

export function WorkspacePage({ rightVisible, setRightVisible }: WorkspacePageProps) {
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [persistedTurns, setPersistedTurns] = useState<PersistedTurn[]>([])
  const [liveTurnId, setLiveTurnId] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [rightTab, setRightTab] = useState<ExecutionTraceTab>('trace')
  const [showLatest, setShowLatest] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [turnFailed, setTurnFailed] = useState(false)
  const { selectedId, selectedState, runtimes, startSession, selectSession, resetSession, toggleSession } = useExecutionRegistry()
  const feedRef = useRef<HTMLDivElement>(null)
  const autoFollowRef = useRef(true)
  const previousFinalTextRef = useRef('')
  const submissionStartedRef = useRef(false)

  const displayedExecution = executionForTurnSubmission(selectedState, submitting ? 'pending' : turnFailed ? 'failed' : null)
  const running = submitting || selectedState.status === 'running' || selectedState.status === 'loading'
  const mappedTurns = useMemo(() => persistedTurnsToConversationTurns(persistedTurns), [persistedTurns])
  const liveTurn = useMemo<ConversationTurn | null>(() => {
    if (!liveTurnId) return null
    const persisted = persistedTurns.find((turn) => turn.id === liveTurnId)
    const question = persisted?.userMessage?.text ?? ''
    const attachments = persisted?.userMessage?.attachments
    // 覆盖为真实 turnId：让 ConversationFeed 识别该 turn 为 live（传 onToggleExecution），
    // 从而执行块使用 live executionExpanded（运行中展开），而不是被本地 historyExpanded 缓存成折叠。
    return { ...liveExecutionToTurn(question, selectedState, attachments), id: liveTurnId }
  }, [liveTurnId, persistedTurns, selectedState])
  const displayTurns = useMemo(() => {
    if (!liveTurn || !liveTurnId) return mappedTurns
    return mappedTurns.map((turn) => (turn.id === liveTurnId ? liveTurn : turn))
  }, [mappedTurns, liveTurn, liveTurnId])
  const rightTrace = useMemo(() => {
    if (liveTurn && liveTurnId) return liveExecutionToTrace(selectedState)
    const lastAgent = [...persistedTurns].reverse().find((turn) => turn.kind === 'agent_task' && turn.execution)
    if (lastAgent?.execution) return executionSnapshotToTraceView(lastAgent.execution)
    return liveExecutionToTrace(selectedState)
  }, [liveTurn, liveTurnId, selectedState, persistedTurns])
  // 底部 Agent Console 的「当前任务」状态：有 liveTurn 只看它；否则只看最新 persisted turn（不回退历史 agent task）
  const taskExecution = useMemo<ExecutionState | null>(
    () => selectTaskExecution(Boolean(liveTurn && liveTurnId), displayedExecution, persistedTurns),
    [liveTurn, liveTurnId, displayedExecution, persistedTurns],
  )
  const showTaskStatus = useMemo(() => Boolean(taskExecution && hasAgentTaskSignals(taskExecution)), [taskExecution])
  const consoleElapsed = useElapsedTime(
    taskExecution?.startedAt ?? null,
    taskExecution?.endedAt ?? null,
    taskExecution?.status === 'running' || taskExecution?.status === 'loading',
  )

  const loadSessions = async () => { try { setSessions((await getSessions()).sessions) } catch (reason) { setError(handleApiError(reason)) } }
  const reloadConversation = useCallback(async (sessionId: string) => {
    try {
      const result = await getSessionMessages(sessionId)
      setPersistedTurns(result.turns)
      const active = activeStatuses.has(result.status)
      const last = result.turns.at(-1)
      if (active && last) {
        setLiveTurnId(last.id)
        startSession(sessionId)
      } else {
        setLiveTurnId(null)
      }
    } catch (reason) { setError(handleApiError(reason)) }
  }, [startSession])
  useEffect(() => { void loadSessions() }, [])
  useEffect(() => { sessionStorage.removeItem('secgo.pendingQuestion') }, [])
  const terminalCount = useMemo(() => Object.values(runtimes).filter((runtime) => ['completed', 'cancelled', 'error', 'awaiting_input'].includes(runtime.state.status)).length, [runtimes])
  useEffect(() => { if (terminalCount > 0) void loadSessions() }, [terminalCount])
  useEffect(() => {
    if (submitting && selectedState.status === 'running') {
      submissionStartedRef.current = true
      setSubmitting(false)
      setTurnFailed(false)
    }
  }, [selectedState.status, submitting])
  // 当前 live turn 到达终态（engine:end / engine:awaiting_input）后，从服务端刷新 conversation 与侧栏
  useEffect(() => {
    if (liveTurnId && ['completed', 'cancelled', 'error', 'awaiting_input'].includes(selectedState.status) && selectedId) {
      void reloadConversation(selectedId)
      void loadSessions()
    }
  }, [liveTurnId, selectedState.status, selectedId, reloadConversation])
  useEffect(() => {
    const text = liveTurn?.finalAnswer ?? ''
    if (!liveTurn?.isFinalStreaming || text === previousFinalTextRef.current) {
      previousFinalTextRef.current = text
      return
    }
    const feed = feedRef.current
    if (feed && shouldFollowStreamUpdate(autoFollowRef.current)) {
      feed.scrollTo({ top: feed.scrollHeight })
      setShowLatest(false)
    } else if (feed) setShowLatest(true)
    previousFinalTextRef.current = text
  }, [liveTurn?.finalAnswer, liveTurn?.isFinalStreaming])
  useEffect(() => {
    const feed = feedRef.current
    if (feed && !autoFollowRef.current && (selectedState.timeline.length || selectedState.keyProgress.length)) setShowLatest(true)
  }, [selectedState.timeline.length, selectedState.keyProgress.length, selectedState.currentActivity])

  useEffect(() => {
    const stored = sessionStorage.getItem('secgo.sessionId')
    if (stored) void select(stored)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const select = async (id: string) => {
    setLoading(true); setError(''); selectSession(id); sessionStorage.setItem('secgo.sessionId', id)
    try {
      await reloadConversation(id)
      requestAnimationFrame(() => feedRef.current?.scrollTo({ top: 0 }))
    }
    catch (reason) { setError(handleApiError(reason)) } finally { setLoading(false) }
  }
  const create = () => {
    selectSession(null); setPersistedTurns([]); setLiveTurnId(null)
    sessionStorage.removeItem('secgo.sessionId')
  }
  const send = async (text: string, attachmentIds: string[], attachments: MessageAttachment[]) => {
    const questionText = text || '请分析这些附件。'
    const targetId = selectedId
    submissionStartedRef.current = false; setSubmitting(true); setTurnFailed(false); setError(''); autoFollowRef.current = true; setShowLatest(false)
    requestAnimationFrame(() => { const feed = feedRef.current; if (feed) feed.scrollTo({ top: feed.scrollHeight }) })
    try {
      const result = await sendChat(text, targetId ?? undefined, attachmentIds)
      const id = result.sessionId
      const turnId = result.turnId
      if (id) {
        startSession(id)
        resetSession(id)
        if (!targetId) {
          selectSession(id)
          sessionStorage.setItem('secgo.sessionId', id)
          setSessions((previous) => [{ id, title: questionText.slice(0, 30), messageCount: 0, stepCount: 0, status: 'queued', createdAt: Date.now(), updatedAt: Date.now() }, ...previous.filter((session) => session.id !== id)])
        }
        // 乐观追加新 Turn（普通 direct_response 也是正式 Turn），等待 SSE 实时更新其 execution
        if (turnId) {
          setPersistedTurns((previous) => {
            if (previous.some((turn) => turn.id === turnId)) return previous
            return [...previous, {
              id: turnId, sessionId: id, sequence: previous.length + 1,
              kind: 'direct_response', userMessage: { text: questionText, attachments },
              assistantAnswer: null, execution: null, status: 'running',
              createdAt: Date.now(), updatedAt: Date.now(),
            }]
          })
          setLiveTurnId(turnId)
        }
      }
      await loadSessions()
    } catch (reason) {
      if (!submissionStartedRef.current) { setSubmitting(false); setTurnFailed(true) }
      setError(handleApiError(reason))
      throw reason
    }
  }
  const stop = async () => { if (selectedId) try { await cancelSession(selectedId) } catch (reason) { setError(handleApiError(reason)) } }
  const rename = async (session: SessionSummary) => { const title = window.prompt('会话新标题：', session.title); if (title?.trim()) { await renameSession(session.id, title.trim()); await loadSessions() } }
  const remove = async (session: SessionSummary) => { if (!window.confirm('删除该会话？此操作不可恢复。')) return; await deleteSession(session.id); if (session.id === selectedId) create(); await loadSessions() }
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
  return <div className="workspace-page">
    <div className="workspace-body">
      <div className="panel-shell left-panel-shell expanded"><Sidebar sessions={sessions} currentId={selectedId} onNew={create} onSelect={(id) => void select(id)} onRename={(session) => void rename(session)} onDelete={(session) => void remove(session)} onSettings={() => {}} /></div>
      <main className="workspace-center">
      <div className="workspace-scroll" ref={feedRef} onScroll={onFeedScroll}>{loading ? <div className="loading-state">正在加载会话…</div> : <ConversationFeed turns={displayTurns} liveTurnId={liveTurnId} onToggleExecution={() => { if (selectedId) toggleSession(selectedId) }} />}{error && <div className="workspace-error">{error}</div>}</div>
      {showLatest && <button className="return-latest" onClick={returnToLatest}>↓ 回到最新</button>}
      <div className="workspace-input"><TasksDock tasks={displayedExecution.tasks} status={displayedExecution.status} />{showTaskStatus && taskExecution && <TaskStatusBar status={taskExecution.status} phase={taskExecution.phase} activeAgent={taskExecution.activeAgent} currentActivity={taskExecution.currentActivity} elapsedMs={consoleElapsed} toolCount={taskExecution.tools.length} evidenceCount={taskExecution.evidence.length} />}<Composer running={running} onSend={send} onStop={stop} /></div>
      </main>
      {rightVisible
        ? <div className="panel-shell right-panel-shell visible"><RightPanel view={rightTrace} tab={rightTab} onTabChange={setRightTab} onCollapse={() => setRightVisible(false)} /></div>
        : <button type="button" className="right-panel-reopen-tab" onClick={() => setRightVisible(true)} aria-label="展开执行面板"><Icon name="chevron" /></button>}
    </div>
  </div>
}
