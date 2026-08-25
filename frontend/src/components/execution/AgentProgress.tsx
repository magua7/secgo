import type { AgentId, ExecutionStatus } from '../../types/execution'

const agents = [
  { id: 'planner', label: '规划', name: 'Planner' },
  { id: 'research', label: '检索', name: 'Research' },
  { id: 'operator', label: '验证', name: 'Operator' },
  { id: 'builder', label: '报告', name: 'Builder' },
]

export function AgentProgress({ activeAgent, status }: { activeAgent: AgentId; status: ExecutionStatus }) {
  const active = Math.max(0, agents.findIndex((agent) => agent.id === activeAgent))
  return <div className="agent-progress">{agents.map((agent, index) => <div className={`${index < active || status === 'completed' ? 'done' : ''} ${index === active && status === 'running' ? 'active' : ''}`} key={agent.id} title={agent.name}>
    <i>{index < active || status === 'completed' ? '✓' : index + 1}</i><span>{agent.label}<small>{agent.name}</small></span>
  </div>)}</div>
}
