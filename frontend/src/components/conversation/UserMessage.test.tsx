import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { UserMessage } from './UserMessage'

describe('UserMessage', () => {
  it('renders a right-side user identity beside the fitted bubble', () => {
    const { container } = render(<UserMessage>测试消息</UserMessage>)
    expect(screen.getByLabelText('用户')).toBeInTheDocument()
    expect(container.querySelector('.user-message-row .user-message')).toHaveTextContent('测试消息')
  })

  it('shows the vision analysis status on an image attachment card', () => {
    const { container } = render(<UserMessage attachments={[{
      id: 'a1', filename: 'login-error.png', mimeType: 'image/png', kind: 'image', size: 1024,
      analysis: { status: 'analyzed', summary: '登录页面出现数据库错误回显', securityFindings: ['存在数据库错误信息泄露'] },
    }]}>分析截图</UserMessage>)
    expect(container.querySelector('.attachment-analysis')).toHaveTextContent('视觉分析完成')
    expect(container.querySelector('.attachment-name')).toHaveTextContent('login-error.png')
  })

  it('never renders vision summary / security findings as user input', () => {
    const { container } = render(<UserMessage attachments={[{
      id: 'a1', filename: 'login-error.png', mimeType: 'image/png', kind: 'image', size: 1024,
      analysis: { status: 'analyzed', summary: '登录页面出现数据库错误回显', securityFindings: ['存在数据库错误信息泄露'] },
    }]}>分析截图</UserMessage>)
    // 系统分析内容绝不伪装成用户输入
    expect(container.querySelector('.attachment-summary')).not.toBeInTheDocument()
    expect(container.textContent).not.toContain('登录页面出现数据库错误回显')
    expect(container.textContent).not.toContain('存在数据库错误信息泄露')
  })

  it('shows a graceful message when vision analysis is unavailable', () => {
    const { container } = render(<UserMessage attachments={[{
      id: 'a2', filename: 'shot.png', mimeType: 'image/png', kind: 'image', size: 10,
      analysis: { status: 'skipped_no_vision', summary: '图片已上传，但当前未配置可用视觉模型' },
    }]}>分析截图</UserMessage>)
    expect(container.querySelector('.attachment-analysis')).toHaveTextContent('视觉分析未启用')
  })

  it('renders a non-image attachment as a type card without any vision wording', () => {
    const { container } = render(<UserMessage attachments={[{
      id: 'a3', filename: 'report.pdf', mimeType: 'application/pdf', kind: 'pdf', size: 2048,
      analysis: { status: 'skipped_no_vision', summary: 'PDF 提取正文：机密内容', error: 'no vision' },
    }]}>分析文档</UserMessage>)
    expect(container.querySelector('.attachment-kind')).toHaveTextContent('PDF')
    expect(container.textContent).not.toContain('视觉分析')
    // PDF 提取正文同样不得进入用户消息
    expect(container.textContent).not.toContain('机密内容')
  })
})
