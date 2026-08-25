import { useEffect, useMemo, useRef, useState } from 'react'
import type { LeftPanelMode } from '../../hooks/preferences'
import type { SessionSummary } from '../../types/session'
import { groupSessionsByDate } from '../../utils/sessionGroups'
import { Icon } from '../common/Icon'
import { SessionContextMenu } from './SessionContextMenu'

interface Props {
  mode: LeftPanelMode; sessions: SessionSummary[]; currentId: string | null
  onCycle: () => void; onNew: () => void; onSelect: (id: string) => void
  onRename: (session: SessionSummary) => void; onDelete: (session: SessionSummary) => void; onSettings: () => void
}

export function Sidebar(props: Props) {
  const [query, setQuery] = useState('')
  const [openMenuId, setOpenMenuId] = useState<string | null>(null)
  const [openMenu, setOpenMenu] = useState<{ session: SessionSummary; anchorRect: DOMRect } | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)
  const grouped = useMemo(() => groupSessionsByDate(props.sessions.filter((session) => (session.title || session.id).toLowerCase().includes(query.toLowerCase()))), [props.sessions, query])
  const closeMenu = () => { setOpenMenuId(null); setOpenMenu(null); triggerRef.current = null }
  useEffect(() => {
    if (!openMenu) return
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node
      if (!menuRef.current?.contains(target) && !triggerRef.current?.contains(target)) closeMenu()
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      const trigger = triggerRef.current
      closeMenu()
      trigger?.focus()
    }
    const onResize = () => closeMenu()
    document.addEventListener('pointerdown', onPointerDown)
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('resize', onResize)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('resize', onResize)
    }
  }, [openMenu])
  useEffect(() => { if (openMenu && !props.sessions.some((session) => session.id === openMenu.session.id)) closeMenu() }, [openMenu, props.sessions])
  useEffect(() => { if (props.mode === 'hidden') closeMenu() }, [props.mode])
  if (props.mode === 'hidden') return null
  return <aside className={`sidebar ${props.mode}`}>
    <button className="new-task" onClick={props.onNew}><Icon name="plus" />新建任务</button>
    <label className="session-search"><Icon name="search" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索历史会话" /></label>
    <div className="session-list" onScroll={closeMenu}>{grouped.map((group) => <section key={group.label}>
      <h3 className="session-group-title">{group.label}</h3>
      {group.sessions.length === 0 && <span className="empty-group">暂无会话</span>}
      {group.sessions.map((session) => <div className={`session-row ${props.currentId === session.id ? 'active' : ''}`} key={session.id}>
        <button className="session-main" onClick={() => { closeMenu(); props.onSelect(session.id) }}><span>{session.title || `${session.id.slice(0, 8)}…`}</span><small>{formatActivityTime(session.updatedAt ?? session.createdAt)}</small></button>
         <button type="button" className="session-more-button" aria-label="会话操作" aria-haspopup="menu" aria-expanded={openMenuId === session.id} onClick={(event) => {
           if (openMenuId === session.id) { closeMenu(); return }
           setOpenMenuId(session.id)
           triggerRef.current = event.currentTarget
           setOpenMenu({ session, anchorRect: event.currentTarget.getBoundingClientRect() })
        }}><Icon name="more" /></button>
      </div>)}
    </section>)}</div>
    {openMenu && <SessionContextMenu session={openMenu.session} anchorRect={openMenu.anchorRect} onRename={props.onRename} onDelete={props.onDelete} onClose={closeMenu} menuRef={menuRef} />}
    
  </aside>
}

function formatActivityTime(value: number | string | null) {
  if (value === null || value === '') return ''
  const numeric = typeof value === 'number' ? value : Number(value)
  const date = new Date(Number.isFinite(numeric) ? (numeric < 100_000_000_000 ? numeric * 1000 : numeric) : value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }).format(date)
}
