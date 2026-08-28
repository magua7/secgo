import { useEffect, useState } from 'react'
import type { MessageAttachment } from '../../types/attachment'
import { formatAttachmentSize } from '../../types/attachment'
import { attachmentImageUrl } from '../../services/api'
import { Icon } from '../common/Icon'

const KIND_LABELS: Record<string, string> = {
  image: 'IMG', pdf: 'PDF', zip: 'ZIP', text: 'TXT', log: 'LOG', code: 'CODE',
  json: 'JSON', yaml: 'YAML', openapi: 'OPENAPI', pcap: 'PCAP', sqlite: 'SQLITE', pe: 'PE', elf: 'ELF',
}

const kindLabel = (kind: string): string => KIND_LABELS[kind] ?? 'BIN'

// 简短状态仅用于图片附件（视觉分析完成 / 失败 / 未启用）；
// PDF/ZIP/TXT 等非图片附件不展示「视觉分析未启用」这类误导性文案。
const imageStatusLabel = (attachment: MessageAttachment): string | null => {
  if (attachment.kind !== 'image' || !attachment.analysis) return null
  if (attachment.analysis.status === 'analyzed') return '✓ 视觉分析完成'
  if (attachment.analysis.status === 'failed') return `✕ 视觉分析失败${attachment.analysis.error ? `：${attachment.analysis.error}` : ''}`
  return '视觉分析未启用'
}

function AttachmentCard({ attachment, sessionId, onPreview }: { attachment: MessageAttachment; sessionId?: string; onPreview: (attachment: MessageAttachment) => void }) {
  const isImage = attachment.kind === 'image'
  const imageSrc = isImage && sessionId ? attachmentImageUrl(sessionId, attachment.id) : null
  const status = imageStatusLabel(attachment)
  return <span className={`attachment-card${isImage ? ' attachment-card-image' : ''}`}>
    {imageSrc
      ? <button type="button" className="attachment-thumb-button" onClick={() => onPreview(attachment)} aria-label={`预览 ${attachment.filename}`}><img className="attachment-thumb" src={imageSrc} alt={attachment.filename} loading="lazy" /></button>
      : <i className="attachment-kind" aria-hidden="true">{kindLabel(attachment.kind)}</i>}
    <span className="attachment-name">{attachment.filename}</span>
    <small className="attachment-meta">{formatAttachmentSize(attachment.size)}</small>
    {status && <small className="attachment-analysis">{status}</small>}
  </span>
}

export function UserMessage({ children, attachments, sessionId }: { children: string; attachments?: MessageAttachment[]; sessionId?: string }) {
  const [preview, setPreview] = useState<MessageAttachment | null>(null)
  useEffect(() => {
    if (!preview) return
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') setPreview(null) }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [preview])
  return <div className="user-message-row">
    <div className="user-message">
      {attachments && attachments.length > 0 && <div className="user-attachments">{attachments.map((attachment) => <AttachmentCard key={attachment.id} attachment={attachment} sessionId={sessionId} onPreview={setPreview} />)}</div>}
      {children && <span>{children}</span>}
    </div>
    <span className="message-user-icon" aria-label="用户"><Icon name="user" /></span>
    {preview && sessionId && <div className="attachment-lightbox" role="dialog" aria-label={`附件预览 ${preview.filename}`} onClick={() => setPreview(null)}>
      <img src={attachmentImageUrl(sessionId, preview.id)} alt={preview.filename} onClick={(event) => event.stopPropagation()} />
      <button type="button" className="attachment-lightbox-close" aria-label="关闭预览" onClick={() => setPreview(null)}><Icon name="close" /></button>
      <span className="attachment-lightbox-caption">{preview.filename} · {formatAttachmentSize(preview.size)}</span>
    </div>}
  </div>
}
