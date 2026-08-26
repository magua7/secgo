import { useEffect, useRef, useState } from 'react'
import { Icon } from '../common/Icon'
import { handleApiError, uploadAttachment } from '../../services/api'
import { formatAttachmentSize, releaseAttachmentPreview, toPendingAttachments, type MessageAttachment, type PendingAttachment } from '../../types/attachment'

interface Props { running: boolean; onSend: (text: string, attachmentIds: string[], attachments: MessageAttachment[]) => Promise<void>; onStop: () => Promise<void> }

export function Composer({ running, onSend, onStop }: Props) {
  const [value, setValue] = useState('')
  const [files, setFiles] = useState<PendingAttachment[]>([])
  const filesRef = useRef<PendingAttachment[]>([])
  const fileRef = useRef<HTMLInputElement>(null)
  useEffect(() => { filesRef.current = files }, [files])
  useEffect(() => () => filesRef.current.forEach(releaseAttachmentPreview), [])
  const upload = async (attachment: PendingAttachment) => {
    setFiles((items) => items.map((item) => item.id === attachment.id ? { ...item, status: 'uploading', error: undefined } : item))
    try {
      const uploaded = await uploadAttachment(attachment.file)
      setFiles((items) => items.map((item) => item.id === attachment.id ? { ...item, status: 'uploaded', attachmentId: uploaded.id, kind: uploaded.kind, error: undefined } : item))
    } catch (reason) {
      setFiles((items) => items.map((item) => item.id === attachment.id ? { ...item, status: 'error', error: handleApiError(reason) } : item))
    }
  }
  const selectFiles = (selected: FileList | null) => {
    files.forEach(releaseAttachmentPreview)
    const next = toPendingAttachments(selected)
    setFiles(next)
    next.forEach((attachment) => void upload(attachment))
  }
  const removeFile = (id: string) => setFiles((items) => {
    const target = items.find((item) => item.id === id)
    if (target) releaseAttachmentPreview(target)
    return items.filter((item) => item.id !== id)
  })
  const uploading = files.some((file) => file.status === 'uploading' || file.status === 'pending')
  const submit = async () => {
    const text = value.trim()
    if ((!text && !files.length) || running || uploading || files.some((file) => file.status === 'error')) return
    const attachments: MessageAttachment[] = files.flatMap((file) => file.attachmentId ? [{ id: file.attachmentId, filename: file.name, mimeType: file.mimeType, kind: file.kind ?? 'binary', size: file.size }] : [])
    try { await onSend(text, attachments.map((attachment) => attachment.id), attachments) }
    catch { return }
    setValue(''); files.forEach(releaseAttachmentPreview); setFiles([])
  }
  return <div className="composer-wrap">
    {files.length > 0 && <div className="local-files">{files.map((file) => <span key={file.id}>{file.previewUrl && <img src={file.previewUrl} alt={file.name} width="28" height="28" />}{file.name} <small>{formatAttachmentSize(file.size)} · {file.status === 'uploading' ? '上传中' : file.status === 'uploaded' ? '已上传' : file.status === 'error' ? file.error || '上传失败' : '待上传'}</small>{file.status === 'error' && <button type="button" onClick={() => void upload(file)}>重试</button>}<button type="button" aria-label={`删除附件 ${file.name}`} onClick={() => removeFile(file.id)}><Icon name="close" /></button></span>)}</div>}
    <div className="composer">
      <textarea aria-label="继续提问" value={value} onChange={(event) => setValue(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void submit() } }} placeholder="继续提问，或补充任务约束……" disabled={running} />
      <div className="composer-actions">
        <input ref={fileRef} hidden type="file" multiple onChange={(event) => { selectFiles(event.target.files); event.currentTarget.value = '' }} />
        <button onClick={() => fileRef.current?.click()}><Icon name="paperclip" />附件</button>
        <button onClick={() => setValue('/skill list')}>/ 命令</button>
        {running ? <button className="stop-button" onClick={() => void onStop()}><Icon name="stop" />停止</button> : <button className="send-button" onClick={() => void submit()} aria-label="发送" disabled={uploading}><Icon name="send" /></button>}
      </div>
    </div>
  </div>
}
