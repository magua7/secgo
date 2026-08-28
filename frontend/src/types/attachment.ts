export type AttachmentStatus = 'pending' | 'uploading' | 'uploaded' | 'error'

// 图片视觉分析状态：analyzed=已分析 / skipped_no_vision=未配置视觉模型 / failed=分析失败
export type VisionAnalysisStatus = 'analyzed' | 'skipped_no_vision' | 'failed'

// 图片附件的结构化视觉分析结果（不含 SHA256 / 服务器路径等内部信息）
export interface AttachmentAnalysis {
  status: VisionAnalysisStatus
  summary?: string
  securityFindings?: string[]
  sceneTags?: string[]
  confidence?: string
  error?: string
}

// 用户消息里展示的结构化附件（不含 SHA256 / 服务器路径等内部信息）
export interface MessageAttachment {
  id: string
  filename: string
  mimeType: string
  kind: string
  size: number
  analysis?: AttachmentAnalysis
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

export const toPendingAttachments = (files: FileList | File[] | null): PendingAttachment[] =>
  Array.from(files ?? []).map((file, index) => ({
    id: `${file.name}-${file.lastModified}-${index}`,
    file,
    name: file.name,
    size: file.size,
    mimeType: file.type || 'application/octet-stream',
    status: 'pending',
    previewUrl: file.type.startsWith('image/') ? URL.createObjectURL(file) : undefined,
  }))

// 与后端 MAX_ATTACHMENTS_PER_TASK 保持一致（一次任务最多 8 个不重复附件）
export const MAX_ATTACHMENTS = 8

// 粘贴截图的 Blob 通常没有合适文件名（image.png / blob / 空名）→ 生成可读文件名
export const clipboardImageName = (file: File, now: Date = new Date()): string => {
  const generic = !file.name || file.name === 'blob' || /^image\.[a-z0-9]+$/i.test(file.name)
  if (!generic) return file.name
  const subtype = (file.type.split('/')[1] || 'png').replace(/[^a-z0-9]/gi, '') || 'png'
  const pad = (value: number): string => String(value).padStart(2, '0')
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`
  return `截图-${stamp}.${subtype}`
}

export function releaseAttachmentPreview(attachment: PendingAttachment): void {
  if (attachment.previewUrl) URL.revokeObjectURL(attachment.previewUrl)
}

export const formatAttachmentSize = (size: number): string =>
  size < 1024 ? `${size} B` : size < 1024 * 1024 ? `${(size / 1024).toFixed(1)} KB` : `${(size / 1024 / 1024).toFixed(1)} MB`
