import type { TodoItem } from '../../types/session'

export function TasksDock({ tasks, status }: { tasks: TodoItem[]; status: string }) {
  if (!tasks.length) return null
  const done = tasks.filter((task) => task.done).length
  const complete = status === 'completed'
  return <details className={`tasks-dock ${complete ? 'completed' : ''}`} open={!complete}>
    <summary>{complete ? `✓ ${done} / ${tasks.length} 任务已完成` : `任务清单 ${done} / ${tasks.length}`}</summary>
    <div className="tasks-dock-list" role="list">{tasks.map((task) => <span role="listitem" key={task.text} className={task.done ? 'done' : ''}>{task.done ? '✓' : '○'} {task.text}</span>)}</div>
  </details>
}
