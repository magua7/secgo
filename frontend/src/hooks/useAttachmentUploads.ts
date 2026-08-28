import { useEffect, useRef, useState } from 'react'
import { handleApiError, uploadAttachment } from '../services/api'
import { MAX_ATTACHMENTS, releaseAttachmentPreview, toPendingAttachments, type PendingAttachment } from '../types/attachment'

export const MAX_ATTACHMENTS_ERROR = `一次任务最多上传 ${MAX_ATTACHMENTS} 个附件`

export interface AttachmentUploads {
  files: PendingAttachment[]
  addFiles: (input: FileList | File[] | null) => void
  removeFile: (id: string) => void
  retry: (attachment: PendingAttachment) => void
  clearFiles: () => void
  uploading: boolean
}

// 统一附件上传管线（文件选择 / 拖拽 / 剪贴板粘贴共用这一套，绝不出现第二套上传逻辑）：
// 去重 → 数量上限 → 逐个 uploadAttachment → 状态回写 / 失败重试 / 预览释放。
export function useAttachmentUploads(): AttachmentUploads {
  const [files, setFiles] = useState<PendingAttachment[]>([])
  const filesRef = useRef<PendingAttachment[]>([])
  const startedRef = useRef(new Set<string>())
  useEffect(() => { filesRef.current = files }, [files])
  useEffect(() => () => {
    filesRef.current.forEach(releaseAttachmentPreview)
    startedRef.current.clear()
  }, [])
  const upload = async (attachment: PendingAttachment) => {
    if (startedRef.current.has(attachment.id)) return
    startedRef.current.add(attachment.id)
    setFiles((items) => items.map((item) => item.id === attachment.id ? { ...item, status: 'uploading', error: undefined } : item))
    try {
      const uploaded = await uploadAttachment(attachment.file)
      setFiles((items) => items.map((item) => item.id === attachment.id ? { ...item, status: 'uploaded', attachmentId: uploaded.id, kind: uploaded.kind, error: undefined } : item))
    } catch (reason) {
      startedRef.current.delete(attachment.id)
      setFiles((items) => items.map((item) => item.id === attachment.id ? { ...item, status: 'error', error: handleApiError(reason) } : item))
    }
  }
  const addFiles = (input: FileList | File[] | null) => {
    const incoming = toPendingAttachments(input)
    if (!incoming.length) return
    const accepted: PendingAttachment[] = []
    const overflow: PendingAttachment[] = []
    const known = filesRef.current
    for (const item of incoming) {
      if (known.some((existing) => existing.id === item.id) || accepted.some((existing) => existing.id === item.id)) {
        releaseAttachmentPreview(item)
        continue
      }
      if (known.length + accepted.length >= MAX_ATTACHMENTS) {
        overflow.push({ ...item, status: 'error', error: MAX_ATTACHMENTS_ERROR })
      } else {
        accepted.push(item)
      }
    }
    if (accepted.length) {
      setFiles((items) => {
        const merged = [...items]
        accepted.forEach((item) => { if (!merged.some((existing) => existing.id === item.id)) merged.push(item) })
        return merged
      })
      accepted.forEach((item) => void upload(item))
    }
    if (overflow.length) {
      setFiles((items) => [...items, ...overflow.filter((item) => !items.some((existing) => existing.id === item.id))])
    }
  }
  const removeFile = (id: string) => {
    startedRef.current.delete(id)
    setFiles((items) => {
      const target = items.find((item) => item.id === id)
      if (target) releaseAttachmentPreview(target)
      return items.filter((item) => item.id !== id)
    })
  }
  const retry = (attachment: PendingAttachment) => {
    startedRef.current.delete(attachment.id)
    void upload(attachment)
  }
  const clearFiles = () => {
    filesRef.current.forEach(releaseAttachmentPreview)
    startedRef.current.clear()
    setFiles([])
  }
  return { files, addFiles, removeFile, retry, clearFiles, uploading: files.some((file) => file.status === 'uploading' || file.status === 'pending') }
}
