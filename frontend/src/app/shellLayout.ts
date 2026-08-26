import type { CSSProperties } from 'react'

export const WORKSPACE_LEFT_WIDTH = '250px'
export const RIGHT_EXPANDED_VAR = 'var(--workspace-right-expanded)'

/**
 * TopBar 中心导航需要与「中央 Workspace 列」的真实水平中心对齐。
 * 该中心相对 viewport center 的偏移 = (leftWidth - rightWidth) / 2，
 * 通过 --shell-left-width / --shell-right-width 两个变量交给 CSS calc 计算，
 * 避免任何 magic margin / translateX 硬编码。
 * 首页没有左右栏，两个变量都是 0，导航严格 viewport 居中。
 */
export function shellPanelVars(isWorkspace: boolean, rightVisible: boolean): CSSProperties {
  return {
    '--shell-left-width': isWorkspace ? WORKSPACE_LEFT_WIDTH : '0px',
    '--shell-right-width': isWorkspace && rightVisible ? RIGHT_EXPANDED_VAR : '0px',
  } as CSSProperties
}
