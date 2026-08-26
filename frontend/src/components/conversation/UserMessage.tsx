import type { MessageAttachment } from '../../types/attachment'
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

export function UserMessage({ children, attachments }: { children: string; attachments?: MessageAttachment[] }) {
  return <div className="user-message-row">
    <div className="user-message">
      {attachments && attachments.length > 0 && <div className="user-attachments">{attachments.map((attachment) => <div className="attachment-card" key={attachment.id}><Icon name="paperclip" /><span className="attachment-name">{attachment.filename}</span><small>{kindLabel(attachment.kind)} · {formatAttachmentSize(attachment.size)}</small></div>)}</div>}
      {children && <span>{children}</span>}
    </div>
    <span className="message-user-icon" aria-label="用户"><Icon name="user" /></span>
  </div>
}
