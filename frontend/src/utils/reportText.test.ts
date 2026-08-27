import { describe, expect, it } from 'vitest'
import { normalizeReportText } from './reportText'

describe('normalizeReportText', () => {
  it('converts report checkbox lines into ✓ / ○ glyph list items (勾代替叉)', () => {
    const input = [
      'TODO:',
      '- [x] 验证假设并提取 flag',
      '- [X] Operator 对目标 URL 进行初始信息收集与页面探索',
      '- [ ] 持久化访问确认（未完成步骤）',
      '',
      '# 🏁 最终研判报告',
    ].join('\n')
    const output = normalizeReportText(input)
    expect(output).toContain('- ✓ 验证假设并提取 flag')
    expect(output).toContain('- ✓ Operator 对目标 URL 进行初始信息收集与页面探索')
    expect(output).toContain('- ○ 持久化访问确认（未完成步骤）')
    expect(output).not.toContain('[x]')
    expect(output).not.toContain('[ ]')
  })

  it('drops TODO labels and internal control-tool narration lines', () => {
    const input = [
      'TODO:',
      '- [x] 探索目标站点结构，确认是否存在文件上传点及可上传 .htaccess 的路径',
      '任务已完成，现在调用 task_complete 结束任务。',
    ].join('\n')
    const output = normalizeReportText(input)
    expect(output).not.toMatch(/^TODO:/m)
    expect(output).not.toContain('task_complete')
    expect(output).toContain('- ✓ 探索目标站点结构')
  })

  it('keeps fenced code blocks untouched', () => {
    const input = ['# 报告', '', '```http', '- [ ] POST /check.php', 'Cookie: role=admin', '```'].join('\n')
    const output = normalizeReportText(input)
    expect(output).toContain('```http\n- [ ] POST /check.php\nCookie: role=admin\n```')
  })

  it('supports ordered checkbox items and returns empty for blank input', () => {
    expect(normalizeReportText('1. [X] 上传恶意 .htaccess')).toBe('1. ✓ 上传恶意 .htaccess')
    expect(normalizeReportText(null)).toBe('')
    expect(normalizeReportText('')).toBe('')
  })
})
