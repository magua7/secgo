import { useEffect, useId, useState } from 'react'
import { buildSetupPayload, getKeysStatus, handleApiError, logout, saveSetup, validateSetupForSave } from '../../services/api'
import type { KeysStatus, ModelConfigInput } from '../../types/api'
import { Icon } from './Icon'
import type { Theme } from '../../hooks/preferences'

const providerSuggestions = ['openai', 'deepseek', 'openrouter', 'anthropic', 'google', 'ollama', 'lm-studio', 'custom']

const blank = (): ModelConfigInput => ({ provider: '', base_url: '', model: '', api_key: '' })

type SettingsSection = 'general' | 'models' | 'appearance'

export function SettingsPanel({ standalone = false, onClose, theme = 'light', onThemeToggle }: { standalone?: boolean; onClose?: () => void; theme?: Theme; onThemeToggle?: () => void }) {
  const [section, setSection] = useState<SettingsSection>('models')
  const [status, setStatus] = useState<KeysStatus | null>(null)
  const [defaultConfig, setDefaultConfig] = useState<ModelConfigInput>(blank())
  const [plannerEnabled, setPlannerEnabled] = useState(false)
  const [planner, setPlanner] = useState<ModelConfigInput>(blank())
  const [validateKeys, setValidateKeys] = useState(true)
  const [message, setMessage] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => { void getKeysStatus().then((data) => {
    setStatus(data)
    if (data.default) setDefaultConfig({ ...data.default, api_key: '' })
    if (data.planner) { setPlanner({ ...data.planner, api_key: '' }); setPlannerEnabled(true) }
  }).catch((error) => setMessage(handleApiError(error))) }, [])

  const save = async (event: React.FormEvent) => {
    event.preventDefault(); setMessage(''); setSaving(true)
    try {
      const validationError = validateSetupForSave(defaultConfig, plannerEnabled ? planner : null)
      if (validationError) throw new Error(validationError)
      const result = await saveSetup(buildSetupPayload(defaultConfig, plannerEnabled ? planner : null, validateKeys))
      setMessage('配置已安全保存')
      if (standalone) window.location.assign(result.next || '/')
    } catch (error) { setMessage(handleApiError(error)) } finally { setSaving(false) }
  }
  const togglePlanner = () => setPlannerEnabled((enabled) => {
    if (!enabled && !planner.provider && !planner.base_url && !planner.model) {
      setPlanner({ ...defaultConfig, api_key: '' })
    }
    return !enabled
  })
  return <div className={standalone ? 'settings-standalone page-texture' : 'settings-overlay'}>
    <section className="settings-panel" aria-label="设置">
      <header><div><span className="eyebrow">SEC-GO SETTINGS</span><h1>设置</h1></div>{onClose && <button className="icon-button" onClick={onClose} aria-label="关闭设置"><Icon name="close" /></button>}</header>
      <div className="settings-layout"><nav aria-label="设置分类">
        <button className={section === 'general' ? 'active' : ''} onClick={() => setSection('general')}><Icon name="settings" />常规</button>
        <button className={section === 'models' ? 'active' : ''} onClick={() => setSection('models')}>◇ 模型配置</button>
        <button className={section === 'appearance' ? 'active' : ''} onClick={() => setSection('appearance')}>◐ 外观</button>
      </nav><form onSubmit={(event) => void save(event)}><div className="settings-content">
        {section === 'general' && <section className="settings-section"><h2>常规</h2><div className="settings-notice"><Icon name="user" /><div><strong>当前账户已受访问密码保护</strong><p>模型密钥只会提交到当前 SEC-GO 后端，浏览器不保存明文。</p></div></div></section>}
        {section === 'models' && <section className="settings-section"><h2>模型配置</h2><p>填写一套「默认模型」即可正常使用；任务规划智能体（Planner）默认复用该模型，如需给它单独指定更强的模型，可展开下方「高级」选项。</p><ModelFields title="默认模型（必填）" required value={defaultConfig} masked={status?.default?.api_key_masked} onChange={setDefaultConfig} /><div className="agent-model-section"><h3>高级：任务规划模型（可选）</h3><div className="switch-row"><span><strong>任务规划模型（Planner）</strong><small>{plannerEnabled ? '已单独指定模型' : '复用默认模型'}</small></span><button type="button" role="switch" aria-label="任务规划模型使用独立模型" aria-checked={plannerEnabled} className={`toggle-control ${plannerEnabled ? 'enabled' : ''}`} onClick={togglePlanner}><span className="toggle-thumb" /></button></div>{plannerEnabled && <ModelFields title="任务规划模型（Planner）" value={planner} masked={status?.planner?.api_key_masked} onChange={setPlanner} />}</div></section>}
        {section === 'appearance' && <section className="settings-section"><h2>外观</h2><div className="appearance-row"><span>主题</span><button type="button" onClick={onThemeToggle}>{theme === 'light' ? '浅色' : '深色'} · 点击切换</button></div></section>}
        {section === 'models' && <label className="check-row"><input type="checkbox" checked={validateKeys} onChange={(event) => setValidateKeys(event.target.checked)} />保存前发送最小请求校验 API Key</label>}
        {message && <p className="settings-message">{message}</p>}
      </div><footer><button type="button" className="text-button danger" onClick={() => void logout().finally(() => window.location.assign('/login'))}>退出登录</button>{section === 'models' && <button className="primary-button" disabled={saving}>{saving ? '正在校验并保存…' : '保存设置'}</button>}</footer></form></div>
    </section>
  </div>
}

function ModelFields({ title, value, masked, required = false, onChange }: { title: string; value: ModelConfigInput; masked?: string; required?: boolean; onChange: (value: ModelConfigInput) => void }) {
  const providerListId = useId()
  const set = (field: keyof ModelConfigInput, next: string) => onChange({ ...value, [field]: next })
  return <fieldset><legend>{title}<span>{required ? '必填' : '可选'}</span></legend>
    <label>Provider<input role="combobox" aria-label={`${title} Provider`} list={providerListId} value={value.provider} onChange={(event) => set('provider', event.target.value)} required /><datalist id={providerListId}>{providerSuggestions.map((provider) => <option key={provider} value={provider} />)}</datalist></label>
    <label>Base URL<input value={value.base_url} onChange={(event) => set('base_url', event.target.value)} required /></label>
    <label>Model ID<input value={value.model} onChange={(event) => set('model', event.target.value)} required /></label>
    <label><span className="field-label-row"><span>API Key</span>{masked && <small className="key-mask">已配置 {masked}</small>}</span><input aria-label={`${title} API Key`} type="password" value={value.api_key ?? ''} onChange={(event) => set('api_key', event.target.value)} placeholder="输入 API Key" required /><small className="field-hint">保存修改时需重新输入 API Key</small></label>
  </fieldset>
}
