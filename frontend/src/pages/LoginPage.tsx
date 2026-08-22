import { useState } from 'react'
import { getKeysStatus, login, handleApiError, resolvePostLoginDestination } from '../services/api'
import type { Theme } from '../hooks/preferences'
import { Brand } from '../components/common/Brand'
import { Icon } from '../components/common/Icon'

export function LoginPage({ initialTheme: _initialTheme }: { initialTheme: Theme }) {
  const [password, setPassword] = useState('')
  const [visible, setVisible] = useState(false)
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(false)
  const submit = async (event: React.FormEvent) => {
    event.preventDefault(); if (!password) { setMessage('请输入访问密码'); return }
    setLoading(true); setMessage('')
    try { await login(password); const status = await getKeysStatus(); window.location.assign(resolvePostLoginDestination(status.ready)) }
    catch (error) { setMessage(handleApiError(error)); setLoading(false) }
  }
  return <main data-testid="login-shell" className={`login-page page-texture ${visible ? 'reveal-dark' : ''}`}>
    <section className="login-card">
      <Brand />
      <div className="ornament-title"><i /><h1>登录</h1><i /></div>
      <p>请输入访问密码以进入系统</p>
      <form onSubmit={(event) => void submit(event)}>
        <label>账号<div className="login-input"><Icon name="user" /><input value="用户" readOnly aria-label="账号" /></div></label>
        <label>密码<div className="login-input password-input"><span data-testid="password-beam" data-direction="left" className={visible ? 'beam visible' : 'beam'}><i /><i /></span><input aria-label="密码" type={visible ? 'text' : 'password'} value={password} onChange={(event) => setPassword(event.target.value)} autoFocus /><button type="button" onClick={() => setVisible((value) => !value)} aria-label={visible ? '隐藏密码' : '显示密码'}><Icon name={visible ? 'eyeOff' : 'eye'} /></button></div></label>
        {message && <div className="login-message">{message}</div>}
        <button className="login-submit" disabled={loading}>{loading ? '正在进入…' : <>进入系统 <span>→</span></>}</button>
      </form>
      <div className="login-role"><i /><span><Icon name="user" /> 用户</span><i /></div>
    </section>
  </main>
}
