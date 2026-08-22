import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ReportView } from './ReportView'

describe('ReportView markdown rendering', () => {
  it('renders ordered lists and strong emphasis instead of exposing markdown markers', () => {
    render(<ReportView report={'1. **侦察** — 信息收集\n2. **扫描与分析** — 指纹识别'} />)

    expect(screen.getByRole('list')).toBeInTheDocument()
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    expect(screen.getByText('侦察').tagName).toBe('STRONG')
    expect(screen.queryByText(/\*\*侦察\*\*/)).not.toBeInTheDocument()
  })

  it('repairs emphasis markers escaped by the model without changing fenced code', () => {
    render(<ReportView report={'1. \\*\\*侦察\\*\\* — 信息收集\n\n```text\n\\*\\*代码里的星号\\*\\*\n```'} />)

    expect(screen.getByText('侦察').tagName).toBe('STRONG')
    expect(screen.getByText('\\*\\*代码里的星号\\*\\*')).toBeInTheDocument()
  })
})
