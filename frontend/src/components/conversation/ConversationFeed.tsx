import type { ConversationTurn } from '../../types/conversation'
import { Brand } from '../common/Brand'
import { TurnView } from './TurnView'

export function ConversationFeed({ turns, liveTurnId, onToggleExecution }: { turns: ConversationTurn[]; liveTurnId: string | null; onToggleExecution: () => void }) {
  const empty = turns.length === 0
  return <div className="conversation-feed">
    {empty && <div className="empty-conversation"><Brand /><h2>准备开始新的安全研判</h2><p>输入目标、线索或任务约束，SEC-GO 将组织多智能体完成分析。</p></div>}
    {turns.map((turn) => <TurnView key={turn.id} turn={turn} onToggleExecution={turn.id === liveTurnId ? onToggleExecution : undefined} />)}
  </div>
}
