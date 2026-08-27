import { describe, expect, it } from 'vitest'
import { sanitizeTodoItems } from './todoDisplay'
import type { TodoItem } from '../types/session'

const item = (text: string, done = true): TodoItem => ({ text, done })

describe('sanitizeTodoItems', () => {
  it('drops internal control-tool rows from real planner output (最终汇报并 task_complete)', () => {
    const dirty: TodoItem[] = [
      item('技能路由与技能读取（ctf-solve-mode）'),
      item('Operator 对目标 URL 进行初始信息收集与页面探索'),
      item('根据探索结果分类漏洞类型并制定渗透假设'),
      item('验证假设并提取 flag'),
      item('最终汇报并 task_complete', false),
    ]
    expect(sanitizeTodoItems(dirty).map((task) => task.text)).toEqual([
      '技能路由与技能读取（ctf-solve-mode）',
      'Operator 对目标 URL 进行初始信息收集与页面探索',
      '根据探索结果分类漏洞类型并制定渗透假设',
      '验证假设并提取 flag',
    ])
  })

  it('covers alternate spellings (handoff_to_agent / Task-Complete) and normalizes whitespace', () => {
    expect(sanitizeTodoItems([item('收尾 handoff_to_agent 移交'), item('Task-Complete 收尾'), item('  验证  假设 ')])).toEqual([
      { text: '验证 假设', done: true },
    ])
  })

  it('keeps legitimate business steps untouched', () => {
    const steps = [item('汇总证据，输出最终研判报告'), item('定位注入点并验证')]
    expect(sanitizeTodoItems(steps)).toHaveLength(2)
  })

  it('tolerates null/undefined input', () => {
    expect(sanitizeTodoItems(null)).toEqual([])
    expect(sanitizeTodoItems(undefined)).toEqual([])
  })
})
