import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Composer } from './Composer'

const apiMocks = vi.hoisted(() => ({ uploadAttachment: vi.fn(), handleApiError: vi.fn((error: unknown) => error instanceof Error ? error.message : '上传失败') }))
vi.mock('../../services/api', () => apiMocks)

afterEach(cleanup)

describe('Composer attachments', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:image')
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    apiMocks.uploadAttachment.mockReset()
  })

  const choose = (file: File) => fireEvent.change(document.querySelector('input[type="file"]')!, { target: { files: [file] } })

  it('uploads an image, stores its attachment id, and sends attachment-only', async () => {
    apiMocks.uploadAttachment.mockResolvedValue({ id: 'attachment-1', name: 'a.png', mimeType: 'image/png', kind: 'image', size: 3, sha256: 'hash' })
    const onSend = vi.fn().mockResolvedValue(undefined)
    render(<Composer running={false} onSend={onSend} onStop={vi.fn()} />)

    choose(new File(['png'], 'a.png', { type: 'image/png' }))
    expect(await screen.findByAltText('a.png')).toHaveAttribute('src', 'blob:image')
    await screen.findByText(/已上传/)
    await userEvent.click(screen.getByRole('button', { name: '发送' }))

    expect(onSend).toHaveBeenCalledWith('', ['attachment-1'], [{ id: 'attachment-1', filename: 'a.png', mimeType: 'image/png', kind: 'image', size: 3 }])
    expect(screen.queryByText('a.png')).not.toBeInTheDocument()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:image')
  })

  it('disables send while uploading', () => {
    apiMocks.uploadAttachment.mockReturnValue(new Promise(() => undefined))
    render(<Composer running={false} onSend={vi.fn()} onStop={vi.fn()} />)
    choose(new File(['data'], 'a.txt', { type: 'text/plain' }))
    expect(screen.getByRole('button', { name: '发送' })).toBeDisabled()
  })

  it('keeps failed uploads and shows the error', async () => {
    apiMocks.uploadAttachment.mockRejectedValue(new Error('上传失败：网络异常'))
    render(<Composer running={false} onSend={vi.fn()} onStop={vi.fn()} />)
    choose(new File(['data'], 'bad.txt', { type: 'text/plain' }))
    expect(await screen.findByText(/上传失败：网络异常/)).toBeInTheDocument()
    expect(screen.getByText('bad.txt')).toBeInTheDocument()
  })

  it('releases previews when removing an attachment', async () => {
    apiMocks.uploadAttachment.mockResolvedValue({ id: 'attachment-1', name: 'a.png', mimeType: 'image/png', kind: 'image', size: 3, sha256: 'hash' })
    render(<Composer running={false} onSend={vi.fn()} onStop={vi.fn()} />)
    choose(new File(['png'], 'a.png', { type: 'image/png' }))
    await screen.findByText(/已上传/)
    await userEvent.click(screen.getByRole('button', { name: '删除附件 a.png' }))
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:image')
  })

  it('keeps attachments when sending fails', async () => {
    apiMocks.uploadAttachment.mockResolvedValue({ id: 'attachment-1', name: 'a.txt', mimeType: 'text/plain', kind: 'text', size: 3, sha256: 'hash' })
    render(<Composer running={false} onSend={vi.fn().mockRejectedValue(new Error('发送失败'))} onStop={vi.fn()} />)
    choose(new File(['txt'], 'a.txt', { type: 'text/plain' }))
    await screen.findByText(/已上传/)
    await userEvent.click(screen.getByRole('button', { name: '发送' }))
    await waitFor(() => expect(screen.getByText('a.txt')).toBeInTheDocument())
  })
})
