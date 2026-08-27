/**
 * 终报正文的最小展示层规整：
 * - 报告里的 TODO 复选框由 react-markdown 渲染成字面「[x]/[ ]」（无 remark-gfm），
 *   完成态看起来像一排叉号。这里把复选框转换成明确的 ✓ / ○ 列表图标。
 * - 去掉「TODO:」这类内部清单标签行。
 * - 去掉包含内部控制工具名（task_complete 等）的整行叙述，避免引擎协议词暴露给用户。
 * 代码围栏内的内容一律原样保留；纯空行对 Markdown 无渲染影响，无需额外收缩。
 */
const INTERNAL_CONTROL_LINE_RE = /\bhandoff_to_agent\b|\btask[\s_-]*complete\b/i
const LIST_LABEL_LINE_RE = /^\s*(?:TODO|当前任务追踪|全局TODO)\s*[:：]?\s*$/i
const CHECKBOX_ITEM_RE = /^(\s*(?:[-*+]|\d+[.)])\s+)\[[ xX]\]\s*/

function mapOutsideFences(report: string): string[] {
  let inFence = false
  return String(report ?? '').split('\n').map((line) => {
    if (/^\s*(```|~~~)/.test(line)) {
      inFence = !inFence
      return line
    }
    if (inFence) return line
    if (LIST_LABEL_LINE_RE.test(line)) return ''
    if (INTERNAL_CONTROL_LINE_RE.test(line)) return ''
    const match = line.match(CHECKBOX_ITEM_RE)
    if (!match) return line
    const done = /x/i.test(match[0])
    return `${match[1]}${done ? '✓' : '○'} ${line.slice(match[0].length)}`
  })
}

export function normalizeReportText(report: string | null | undefined): string {
  if (!report) return ''
  return mapOutsideFences(String(report)).join('\n').replace(/^\s+/, '').trim()
}
