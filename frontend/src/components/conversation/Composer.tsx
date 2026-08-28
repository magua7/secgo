import { useRef, useState } from 'react'
import type { ClipboardEvent as ReactClipboardEvent, DragEvent as ReactDragEvent } from 'react'
import { Icon } from '../common/Icon'
import { clipboardImageName, formatAttachmentSize, type MessageAttachment } from '../../types/attachment'
import { MAX_ATTACHMENTS_ERROR, useAttachmentUploads } from '../../hooks/useAttachmentUploads'

interface Props { running: boolean; onSend: (text: string, attachmentIds: string[], attachments: MessageAttachment[]) => Promise<void>; onStop: () => Promise<void> }

export function Composer({ running, onSend, onStop }: Props) {
  const [value, setValue] = useState('')
  const { files, addFiles, removeFile, retry, clearFiles, uploading } = useAttachmentUploads()
  const fileRef = useRef<HTMLInputElement>(null)
  const dragDepthRef = useRef(0)
  const [dragOver, setDragOver] = useState(false)
  const submit = async () => {
    const text = value.trim()
    if ((!text && !files.length) || running || uploading || files.some((file) => file.status === 'error')) return
    const attachments: MessageAttachment[] = files.flatMap((file) => file.attachmentId ? [{ id: file.attachmentId, filename: file.name, mimeType: file.mimeType, kind: file.kind ?? 'binary', size: file.size }] : [])
    try { await onSend(text, attachments.map((attachment) => attachment.id), attachments) }
    catch { return }
    setValue(''); clearFiles()
  }
  // 拖拽上传：与附件按钮共用同一 upload pipeline（useAttachmentUploads），支持所有可上传类型
  const onDragEnter = (event: ReactDragEvent<HTMLDivElement>) => { event.preventDefault(); dragDepthRef.current += 1; setDragOver(true) }
  const onDragLeave = (event: ReactDragEvent<HTMLDivElement>) => {
    event.preventDefault()
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1)
    if (dragDepthRef.current === 0) setDragOver(false)
  }
  const onDrop = (event: ReactDragEvent<HTMLDivElement>) => {
    event.preventDefault()
    dragDepthRef.current = 0
    setDragOver(false)
    addFiles(event.dataTransfer?.files ?? null)
  }
  // 剪贴板粘贴：有文件（截图等）→ 走统一上传；纯文本 Ctrl+V 保持浏览器默认行为
  const onPaste = (event: ReactClipboardEvent<HTMLTextAreaElement>) => {
    const pasted = Array.from(event.clipboardData?.files ?? [])
    if (!pasted.length) return
    event.preventDefault()
    addFiles(pasted.map((file) => {
      const name = clipboardImageName(file)
      return name === file.name ? file : new File([file], name, { type: file.type })
    }))
  }
  return <div
    className={`composer-wrap${dragOver ? ' drag-over' : ''}`}
    onDragEnter={onDragEnter}
    onDragOver={(event) => event.preventDefault()}
    onDragLeave={onDragLeave}
    onDrop={onDrop}
  >
    {files.length > 0 && <div className="local-files">{files.map((file) => <span key={file.id}>{file.previewUrl && <img src={file.previewUrl} alt={file.name} width="28" height="28" />}{file.name} <small>{formatAttachmentSize(file.size)} · {file.status === 'uploading' ? '上传中' : file.status === 'uploaded' ? '已上传' : file.status === 'error' ? file.error || '上传失败' : '待上传'}</small>{file.status === 'error' && file.error !== MAX_ATTACHMENTS_ERROR && <button type="button" onClick={() => retry(file)}>重试</button>}<button type="button" aria-label={`删除附件 ${file.name}`} onClick={() => removeFile(file.id)}><Icon name="close" /></button></span>)}</div>}
    {dragOver && <div className="composer-drop-hint">松开以上传附件</div>}
    <div className="composer">
      <textarea aria-label="继续提问" value={value} onChange={(event) => setValue(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void submit() } }} onPaste={onPaste} placeholder="继续提问，或补充任务约束……" disabled={running} />
      <div className="composer-actions">
        <input ref={fileRef} hidden type="file" multiple onChange={(event) => { addFiles(event.target.files); event.currentTarget.value = '' }} />
        <button onClick={() => fileRef.current?.click()}><Icon name="paperclip" />附件</button>
        <button onClick={() => setValue('/skill list')}>/ 命令</button>
        {running ? <button className="stop-button" onClick={() => void onStop()}><Icon name="stop" />停止</button> : <button className="send-button" onClick={() => void submit()} aria-label="发送" disabled={uploading}><Icon name="send" /></button>}
      </div>
    </div>
  </div>
}
