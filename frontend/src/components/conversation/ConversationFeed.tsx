import type { HistoryMessage, TodoItem } from '../../types/session'
import type { ExecutionState } from '../../types/execution'
import type { ConversationTurn } from '../../types/conversation'
import { Brand } from '../common/Brand'
import { historyMessagesToTurns, liveExecutionToTurn } from './conversationAdapter'
import { TurnView } from './TurnView'

export function ConversationFeed({ messages, todoList, committedTurns, currentQuestion, execution, onToggleExecution }: { messages: HistoryMessage[]; todoList: TodoItem[]; committedTurns: ConversationTurn[]; currentQuestion: string; execution: ExecutionState; onToggleExecution: () => void }) {
  const empty = !messages.length && !committedTurns.length && !currentQuestion && execution.status === 'idle'
  const historicalTurns = historyMessagesToTurns(messages, todoList)
  const showLiveTurn = Boolean(currentQuestion)
  return <div className="conversation-feed">
    {empty && <div className="empty-conversation"><Brand /><h2>准备开始新的安全研判</h2><p>输入目标、线索或任务约束，SEC-GO 将组织多智能体完成分析。</p></div>}
    {historicalTurns.map((turn) => <TurnView key={turn.id} turn={turn} />)}
    {committedTurns.map((turn) => <TurnView key={turn.id} turn={turn} />)}
    {showLiveTurn && <TurnView turn={liveExecutionToTurn(currentQuestion, execution)} onToggleExecution={onToggleExecution} />}
  </div>
}
