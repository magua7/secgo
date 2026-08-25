import { Icon } from '../common/Icon'

export function UserMessage({ children }: { children: string }) {
  return <div className="user-message-row"><div className="user-message">{children}</div><span className="message-user-icon" aria-label="用户"><Icon name="user" /></span></div>
}
