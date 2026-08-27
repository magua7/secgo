import type { AgentId, ExecutionStatus } from '../../types/execution'

const agents = [
  { id: 'planner', label: '规划', name: 'Planner' },
  { id: 'research', label: '检索', name: 'Research' },
  { id: 'operator', label: '验证', name: 'Operator' },
  { id: 'builder', label: '构建', name: 'Builder' },
]

interface Props {
  activeAgent: AgentId
  status: ExecutionStatus
  participatedAgents?: AgentId[]
}

export function AgentProgress({ activeAgent, status, participatedAgents = [] }: Props) {
  const running = status === 'running' || status === 'loading' || status === 'awaiting_input'
  const participated = new Set(participatedAgents)
  return <div className="agent-progress">{agents.map((agent) => {
    const isActive = running && agent.id === activeAgent
    const isParticipated = !isActive && participated.has(agent.id)
    return <div className={`agent-state ${isActive ? 'active' : ''} ${isParticipated ? 'participated' : ''}`} key={agent.id} title={agent.name}>
      <i className="agent-dot" />
      <span>{agent.label}<small>{agent.name}</small></span>
    </div>
  })}</div>
}
