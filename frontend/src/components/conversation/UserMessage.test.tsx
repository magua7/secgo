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
    expect(container.querySelector('.attachment-summary')).toHaveTextContent('登录页面出现数据库错误回显')
    expect(container.querySelector('.attachment-name')).toHaveTextContent('login-error.png')
  })

  it('shows a graceful message when vision analysis is unavailable', () => {
    const { container } = render(<UserMessage attachments={[{
      id: 'a2', filename: 'shot.png', mimeType: 'image/png', kind: 'image', size: 10,
      analysis: { status: 'skipped_no_vision', summary: '图片已上传，但当前未配置可用视觉模型' },
    }]}>分析截图</UserMessage>)
    expect(container.querySelector('.attachment-analysis')).toHaveTextContent('视觉分析未启用')
  })
})
