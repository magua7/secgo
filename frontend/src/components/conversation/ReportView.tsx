import Markdown from 'react-markdown'
import { normalizeReportText } from '../../utils/reportText'
import { stripCursorArtifacts } from "../../utils/textClean";

export function ReportView({ report, streaming = false }: { report: string; streaming?: boolean }) {
  if (!report) return null
  const text = normalizeReportText(stripCursorArtifacts(report ?? ""))
  return <article className={`report-view ${streaming ? 'streaming' : ''}`} aria-label="研判报告">
    <div className="report-kicker"><span>SEC-GO 研判报告</span>{streaming && <i className="stream-caret" />}</div>
    <Markdown>{text}</Markdown>
  </article>
}
