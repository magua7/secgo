import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { HomePage } from './HomePage'

describe('HomePage', () => {
  it('fills the prompt from a capability preset', async () => {
    render(<HomePage theme="light" onThemeToggle={vi.fn()} onOpenSettings={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: /恶意域名研判/ }))
    expect((screen.getByLabelText('安全任务') as HTMLTextAreaElement).value).toContain('域名')
    expect(screen.queryByRole('button', { name: '历史会话' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /快速模式/ })).not.toBeInTheDocument()
    for (const name of ['恶意域名研判', 'Web 风险分析', 'IOC 批量分析', '样本线索归因', 'CVE 风险评估', 'APT 组织画像']) {
      expect(screen.getByRole('button', { name }).querySelector('.capability-icon svg')).toBeInTheDocument()
    }
  })
})
