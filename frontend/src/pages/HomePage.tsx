import { useEffect, useRef, useState } from 'react'
import type { Theme } from '../hooks/preferences'
import { handleApiError, sendChat, uploadAttachment } from '../services/api'
import { Icon } from '../components/common/Icon'
import { formatAttachmentSize, releaseAttachmentPreview, toPendingAttachments, type PendingAttachment } from '../types/attachment'

const capabilities = [
  ['domainShield', '恶意域名研判', '深度解析域名注册、解析、历史及关联风险。', '请对这个域名进行完整的恶意域名安全研判：'],
  ['webScan', 'Web 风险分析', '检测站点威胁、钓鱼、挂马及内容安全风险。', '请分析这个 Web 目标的安全风险：'],
  ['iocRadar', 'IOC 批量分析', '批量查询 IOC 情报，评估风险与关联。', '请批量分析以下 IOC，并归纳关联关系：'],
  ['sampleTrace', '样本线索归因', '提取样本特征与行为线索，追踪攻击链。', '请对以下样本线索进行归因分析：'],
  ['cveShield', 'CVE 风险评估', '评估漏洞影响范围与利用风险，提供修复建议。', '请评估这个 CVE 的实际风险与修复优先级：'],
  ['aptNetwork', 'APT 组织画像', '关联攻击基础设施与战术技法，绘制组织画像。', '请根据以下线索分析可能关联的 APT 组织：'],
] as const

export function HomePage() {
  const [prompt, setPrompt] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [attachments, setAttachments] = useState<PendingAttachment[]>([])
  const attachmentsRef = useRef<PendingAttachment[]>([])
  const fileRef = useRef<HTMLInputElement>(null)
  useEffect(() => { attachmentsRef.current = attachments }, [attachments])
  useEffect(() => () => attachmentsRef.current.forEach(releaseAttachmentPreview), [])
  const upload = async (attachment: PendingAttachment) => {
    setAttachments((items) => items.map((item) => item.id === attachment.id ? { ...item, status: 'uploading', error: undefined } : item))
    try {
      const uploaded = await uploadAttachment(attachment.file)
      setAttachments((items) => items.map((item) => item.id === attachment.id ? { ...item, status: 'uploaded', attachmentId: uploaded.id, kind: uploaded.kind, error: undefined } : item))
    } catch (reason) {
      setAttachments((items) => items.map((item) => item.id === attachment.id ? { ...item, status: 'error', error: handleApiError(reason) } : item))
    }
  }
  const selectFiles = (files: FileList | null) => {
    attachments.forEach(releaseAttachmentPreview)
    const selected = toPendingAttachments(files)
    setAttachments(selected)
    selected.forEach((attachment) => void upload(attachment))
  }
  const removeAttachment = (id: string) => setAttachments((items) => {
    const target = items.find((item) => item.id === id)
    if (target) releaseAttachmentPreview(target)
    return items.filter((item) => item.id !== id)
  })
  const start = async () => {
    const message = prompt.trim(); if (!message && !attachments.length) return
    if (attachments.some((attachment) => attachment.status === 'uploading' || attachment.status === 'pending')) { setError('附件仍在上传，请稍候'); return }
    if (attachments.some((attachment) => attachment.status === 'error')) { setError('存在上传失败的附件，请删除或重试'); return }
    setSubmitting(true); setError('')
    try {
      const question = message || '请分析这些附件。'
      const result = await sendChat(message, undefined, attachments.flatMap((attachment) => attachment.attachmentId ? [attachment.attachmentId] : []))
      sessionStorage.setItem('secgo.sessionId', result.sessionId)
      sessionStorage.setItem('secgo.pendingQuestion', question)
      attachments.forEach(releaseAttachmentPreview); setAttachments([])
      window.location.hash = '#/workspace'
    } catch (reason) { setError(handleApiError(reason)); setSubmitting(false) }
  }
  return <div className="home-page page-texture" style={{ width: "100%", height: "100%", overflow: "auto" }}>
      <main className="home-main">
      <section className="hero"><span className="eyebrow">MULTI-AGENT SECURITY RESEARCH</span><h1>开始一次安全研判</h1><p>输入域名、IP、Hash、CVE、文件线索或授权安全任务，SEC-GO 将为您组织分析、验证与报告。</p>
        <div className="hero-composer">
          <textarea aria-label="安全任务" value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="输入域名、IP、Hash、CVE、文件或描述安全任务……" />
          {attachments.length > 0 && <div className="pending-attachments">{attachments.map((file) => <span key={file.id}>{file.previewUrl && <img src={file.previewUrl} alt={file.name} width="28" height="28" />}{file.name}<small>{formatAttachmentSize(file.size)} · {file.status === 'uploading' ? '上传中' : file.status === 'uploaded' ? '已上传' : file.status === 'error' ? file.error || '上传失败' : '待上传'}</small>{file.status === 'error' && <button type="button" onClick={() => void upload(file)}>重试</button>}<button type="button" aria-label={`删除附件 ${file.name}`} onClick={() => removeAttachment(file.id)}><Icon name="close" /></button></span>)}</div>}
          <div><span className="hero-tools"><input ref={fileRef} hidden type="file" multiple onChange={(event) => { selectFiles(event.target.files); event.currentTarget.value = '' }} /><button onClick={() => fileRef.current?.click()}><Icon name="paperclip" />附件</button><button onClick={() => setPrompt('请对 example.com 进行恶意域名安全研判，并给出证据与处置建议。')}>▣ 示例任务</button></span><button className="primary-button" onClick={() => void start()} disabled={submitting || attachments.some((attachment) => attachment.status === 'uploading' || attachment.status === 'pending')}>{submitting ? '正在创建…' : '开始任务'} <span>→</span></button></div>
        </div>{error && <p className="hero-error">{error}</p>}
      </section>
      <section className="capability-grid">{capabilities.map(([icon, title, desc, preset]) => <button key={title} onClick={() => setPrompt(preset)} aria-label={title}><i className="capability-icon"><Icon name={icon} /></i><h2>{title}</h2><p>{desc}</p><span>→</span></button>)}</section>
      <section className="how"><div className="section-heading"><i /><h2>SEC-GO 如何工作</h2><i /></div><div className="how-grid"><article><b>01</b><i><Icon name="taskAnalysis" /></i><div><h3>任务理解</h3><p>理解任务目标与上下文，提取关键要素并规划分析路径。</p></div></article><article><b>02</b><i><Icon name="agentCollaboration" /></i><div><h3>Agent 协作</h3><p>多智能体协同检索、分析与验证，融合情报和工具能力。</p></div></article><article><b>03</b><i><Icon name="evidenceReport" /></i><div><h3>证据与报告</h3><p>形成结构化证据链与可视化结论，输出可复用安全报告。</p></div></article></div></section>
    </main>
  </div>
}
