import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { UserMessage } from './UserMessage'

describe('UserMessage', () => {
  it('renders a right-side user identity beside the fitted bubble', () => {
    const { container } = render(<UserMessage>测试消息</UserMessage>)
    expect(screen.getByLabelText('用户')).toBeInTheDocument()
    expect(container.querySelector('.user-message-row .user-message')).toHaveTextContent('测试消息')
  })
})
