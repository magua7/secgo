export type AttachmentStatus = 'pending' | 'uploading' | 'uploaded' | 'error'

// 用户消息里展示的结构化附件（不含 SHA256 / 服务器路径等内部信息）
export interface MessageAttachment {
  id: string
  filename: string
  mimeType: string
  kind: string
  size: number
}

export interface PendingAttachment {
  id: string
  file: File
  name: string
  size: number
  mimeType: string
  status: AttachmentStatus
  previewUrl?: string
  attachmentId?: string
  kind?: string
  error?: string
}

export const toPendingAttachments = (files: FileList | null): PendingAttachment[] =>
  Array.from(files ?? []).map((file, index) => ({
    id: `${file.name}-${file.lastModified}-${index}`,
    file,
    name: file.name,
    size: file.size,
    mimeType: file.type || 'application/octet-stream',
    status: 'pending',
    previewUrl: file.type.startsWith('image/') ? URL.createObjectURL(file) : undefined,
  }))

export function releaseAttachmentPreview(attachment: PendingAttachment): void {
  if (attachment.previewUrl) URL.revokeObjectURL(attachment.previewUrl)
}

export const formatAttachmentSize = (size: number): string =>
  size < 1024 ? `${size} B` : size < 1024 * 1024 ? `${(size / 1024).toFixed(1)} KB` : `${(size / 1024 / 1024).toFixed(1)} MB`
