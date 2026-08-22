export interface ScrollMetrics {
  scrollHeight: number
  scrollTop: number
  clientHeight: number
}

export const distanceToBottom = ({ scrollHeight, scrollTop, clientHeight }: ScrollMetrics): number => Math.max(0, scrollHeight - scrollTop - clientHeight)

export const isNearBottom = (metrics: ScrollMetrics, threshold = 100): boolean => distanceToBottom(metrics) < threshold

export const shouldFollowStreamUpdate = (wasFollowingBeforeRender: boolean): boolean => wasFollowingBeforeRender
