import { describe, expect, it, vi } from 'vitest'
import { releaseAttachmentPreview, toPendingAttachments } from './attachment'

describe('attachment types', () => {
  it('keeps the original File and creates and releases image previews', () => {
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:preview')
    const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    const file = new File(['png'], 'sample.png', { type: 'image/png', lastModified: 1 })
    const list = { 0: file, length: 1, item: () => file } as unknown as FileList

    const attachment = toPendingAttachments(list)[0]!

    expect(attachment.file).toBe(file)
    expect(attachment.previewUrl).toBe('blob:preview')
    releaseAttachmentPreview(attachment)
    expect(createObjectURL).toHaveBeenCalledWith(file)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:preview')
  })
})
