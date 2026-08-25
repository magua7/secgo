import { useLayoutEffect, useRef, useState } from 'react'
import { createPortal, flushSync } from 'react-dom'
import type { RefObject } from 'react'
import type { SessionSummary } from '../../types/session'

const MENU_GAP = 7
const VIEWPORT_MARGIN = 8
const FALLBACK_WIDTH = 126
const FALLBACK_HEIGHT = 82

interface Props {
  session: SessionSummary
  anchorRect: DOMRect
  onRename: (session: SessionSummary) => void
  onDelete: (session: SessionSummary) => void
  onClose: () => void
  menuRef: RefObject<HTMLDivElement | null>
}

function placeMenu(anchorRect: DOMRect, width: number, height: number) {
  const maxLeft = Math.max(VIEWPORT_MARGIN, window.innerWidth - VIEWPORT_MARGIN - width)
  const left = Math.min(Math.max(anchorRect.right - width, VIEWPORT_MARGIN), maxLeft)
  const fitsBelow = anchorRect.bottom + MENU_GAP + height <= window.innerHeight - VIEWPORT_MARGIN
  const preferredTop = fitsBelow ? anchorRect.bottom + MENU_GAP : anchorRect.top - MENU_GAP - height
  const maxTop = Math.max(VIEWPORT_MARGIN, window.innerHeight - VIEWPORT_MARGIN - height)
  return { left, top: Math.min(Math.max(preferredTop, VIEWPORT_MARGIN), maxTop), placement: fitsBelow ? 'below' : 'above' }
}

export function SessionContextMenu({ session, anchorRect, onRename, onDelete, onClose, menuRef }: Props) {
  const firstItemRef = useRef<HTMLButtonElement | null>(null)
  const [position, setPosition] = useState(() => placeMenu(anchorRect, FALLBACK_WIDTH, FALLBACK_HEIGHT))
  const closeThen = (action: () => void) => {
    flushSync(onClose)
    action()
  }

  useLayoutEffect(() => {
    const menu = menuRef.current
    if (!menu) return
    const rect = menu.getBoundingClientRect()
    setPosition(placeMenu(anchorRect, rect.width || FALLBACK_WIDTH, rect.height || FALLBACK_HEIGHT))
    firstItemRef.current?.focus()
  }, [anchorRect, menuRef])

  return createPortal(
    <div ref={menuRef} className="session-menu" role="menu" aria-label="会话操作" data-placement={position.placement} style={{ left: position.left, top: position.top }}>
      <button ref={firstItemRef} type="button" role="menuitem" onClick={() => closeThen(() => onRename(session))}>重命名</button>
      <button type="button" role="menuitem" className="danger" onClick={() => closeThen(() => onDelete(session))}>删除</button>
    </div>,
    document.body,
  )
}
