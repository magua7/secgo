import type { AttachmentAnalysis, MessageAttachment } from '../../types/attachment'
import { formatAttachmentSize } from '../../types/attachment'
import { Icon } from '../common/Icon'

const kindLabel = (kind: string): string => {
  if (kind === 'text') return 'TXT'
  if (kind === 'image') return 'IMG'
  if (kind === 'pdf') return 'PDF'
  if (kind === 'pe') return 'PE'
  if (kind === 'elf') return 'ELF'
  if (kind === 'pcap') return 'PCAP'
  if (kind === 'sqlite') return 'SQLITE'
  return 'BIN'
}

const analysisLabel = (analysis?: AttachmentAnalysis): string | null => {
  if (!analysis) return null
  if (analysis.status === 'analyzed') return '✓ 视觉分析完成'
  if (analysis.status === 'failed') return `✕ 视觉分析失败${analysis.error ? `：${analysis.error}` : ''}`
  return '视觉分析未启用'
}

export function UserMessage({ children, attachments }: { children: string; attachments?: MessageAttachment[] }) {
  return <div className="user-message-row">
    <div className="user-message">
      {attachments && attachments.length > 0 && <div className="user-attachments">{attachments.map((attachment) => {
        const label = analysisLabel(attachment.analysis)
        return <div className="attachment-card" key={attachment.id}><Icon name="paperclip" /><span className="attachment-name">{attachment.filename}</span><small>{kindLabel(attachment.kind)} · {formatAttachmentSize(attachment.size)}</small>{label && <small className="attachment-analysis">{label}</small>}{attachment.analysis?.summary && <small className="attachment-summary">{attachment.analysis.summary}</small>}</div>
      })}</div>}
      {children && <span>{children}</span>}
    </div>
    <span className="message-user-icon" aria-label="用户"><Icon name="user" /></span>
  </div>
}
