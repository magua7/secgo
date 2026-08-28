import { useState } from 'react'
import type { ConversationTurn } from '../../types/conversation'
import { Brand } from '../common/Brand'
import { ExecutionBlock } from './ExecutionBlock'
import { ReportView } from './ReportView'
import { UserMessage } from './UserMessage'

export function TurnView({ turn, onToggleExecution }: { turn: ConversationTurn; onToggleExecution?: () => void }) {
  const [historyExpanded, setHistoryExpanded] = useState(turn.execution?.expanded ?? false)
  const hasExecution = turn.kind === 'agent_task' && Boolean(turn.execution)
  const presentation = turn.execution ? (onToggleExecution ? turn.execution : { ...turn.execution, expanded: historyExpanded }) : null
  const toggle = onToggleExecution ?? (() => setHistoryExpanded((value) => !value))
  return <div className="conversation-turn">
    <UserMessage attachments={turn.userMessage.attachments} sessionId={turn.sessionId}>{turn.userMessage.text}</UserMessage>
    {(hasExecution || turn.finalAnswer) && <div className="assistant-message"><Brand compact /><div className="assistant-content">
      {hasExecution && presentation && <ExecutionBlock presentation={presentation} onToggle={toggle} />}
      {turn.finalAnswer && <ReportView report={turn.finalAnswer} />}
    </div></div>}
  </div>
}
