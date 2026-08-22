export function PanelEmptyState({ title, detail }: { title: string; detail?: string }) {
  return <div className="panel-empty" role="status">
    <strong>{title}</strong>
    {detail && <p>{detail}</p>}
  </div>
}
