import Markdown from 'react-markdown'

export function ReportView({ report, streaming = false }: { report: string; streaming?: boolean }) {
  if (!report) return null
  return <article className={`report-view ${streaming ? 'streaming' : ''}`} aria-label="研判报告">
    <div className="report-kicker"><span>SEC-GO 研判报告</span>{streaming && <i className="stream-caret" />}</div>
    <Markdown>{report}</Markdown>
  </article>
}
