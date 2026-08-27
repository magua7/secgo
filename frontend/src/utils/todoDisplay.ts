import type { TodoItem } from '../types/session'

/**
 * 内部控制工具名（task_complete / handoff_to_agent 等）属于引擎协议事件，
 * 绝不应作为用户任务项出现在 TODO 清单或状态文案中。
 * Planner 收尾时会把「最终汇报并 task_complete」写成复选框行，被
 * TodoTracker 误当成任务持久化 —— 这里在展示/入库状态层做最小过滤。
 */
const INTERNAL_CONTROL_TOKEN_RE = /\bhandoff_to_agent\b|\btask[\s_-]*complete\b/i

export function referencesInternalControl(text: string | undefined): boolean {
  return typeof text === 'string' && INTERNAL_CONTROL_TOKEN_RE.test(text)
}

export function normalizeTodoText(text: string): string {
  return String(text ?? '').replace(/\s+/g, ' ').trim()
}

/** 过滤内部控制项，并规整空白；输入可以是旧快照里的脏数据。 */
export function sanitizeTodoItems<T extends TodoItem>(tasks: readonly T[] | null | undefined): TodoItem[] {
  if (!Array.isArray(tasks)) return []
  return tasks
    .filter((item) => Boolean(item) && !referencesInternalControl(item?.text))
    .map((item) => ({ ...item, text: normalizeTodoText(item.text) }))
}
