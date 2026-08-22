import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { LoginPage } from './LoginPage'

vi.mock('../services/api', () => ({ login: vi.fn(), handleApiError: () => '登录失败' }))

describe('LoginPage', () => {
  it('shows only password authentication and projects reveal light left', async () => {
    render(<LoginPage initialTheme="light" />)
    expect(screen.queryByLabelText('API Key')).not.toBeInTheDocument()
    const password = screen.getByLabelText('密码')
    expect(password).toHaveAttribute('type', 'password')
    await userEvent.click(screen.getByRole('button', { name: '显示密码' }))
    expect(password).toHaveAttribute('type', 'text')
    expect(screen.queryByText('默认状态')).not.toBeInTheDocument()
    expect(screen.getByTestId('login-shell')).toHaveClass('reveal-dark')
    expect(screen.getByTestId('password-beam')).toHaveAttribute('data-direction', 'left')
    await userEvent.click(screen.getByRole('button', { name: '隐藏密码' }))
    expect(screen.getByTestId('login-shell')).not.toHaveClass('reveal-dark')
  })
})
