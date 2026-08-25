import { useEffect, useId, useState } from 'react'
import { buildSetupPayload, getKeysStatus, handleApiError, logout, saveSetup, validateSetupForSave } from '../../services/api'
import type { AgentId, AgentOverrideInputs, ConfigId, KeysStatus, ModelConfigInput, ModelKeyStatus, SetupResponse } from '../../types/api'
import { Icon } from './Icon'
import type { Theme } from '../../hooks/preferences'

const providerSuggestions = ['openai', 'deepseek', 'openrouter', 'anthropic', 'google', 'ollama', 'lm-studio', 'custom']
const AGENTS = [
  { id: 'planner', name: 'Planner', role: '规划分析', description: '负责任务拆解、计划生成与执行路径规划。' },
  { id: 'research', name: 'Research', role: '信息检索', description: '负责网络搜索、信息检索与资料收集。' },
  { id: 'builder', name: 'Builder', role: '内容生成', description: '负责文案撰写、代码生成与内容创作。' },
  { id: 'operator', name: 'Operator', role: '任务执行', description: '负责执行操作、调用工具与系统交互。' },
] as const satisfies ReadonlyArray<{ id: AgentId; name: string; role: string; description: string }>

const blank = (): ModelConfigInput => ({ provider: '', base_url: '', model: '', api_key: '' })
const blankAgents = (): AgentOverrideInputs => ({
  planner: { enabled: false, config: blank() },
  research: { enabled: false, config: blank() },
  builder: { enabled: false, config: blank() },
  operator: { enabled: false, config: blank() },
})

type SettingsSection = 'general' | 'models' | 'appearance'
type ValidationState = { state: 'idle' | 'validating' | 'valid' | 'invalid'; message?: string }
type ValidationStates = Record<ConfigId, ValidationState>

const idleValidation = (): ValidationStates => ({
  default: { state: 'idle' },
  planner: { state: 'idle' },
  research: { state: 'idle' },
  builder: { state: 'idle' },
  operator: { state: 'idle' },
})

const fromStatus = (value: ModelKeyStatus): ModelConfigInput => ({
  provider: value.provider,
  base_url: value.base_url,
  model: value.model,
  api_key: '',
})

export function SettingsPanel({ standalone = false, onClose, theme = 'light', onThemeToggle }: { standalone?: boolean; onClose?: () => void; theme?: Theme; onThemeToggle?: () => void }) {
  const [section, setSection] = useState<SettingsSection>('models')
  const [status, setStatus] = useState<KeysStatus | null>(null)
  const [defaultConfig, setDefaultConfig] = useState<ModelConfigInput>(blank())
  const [agentConfigs, setAgentConfigs] = useState<AgentOverrideInputs>(blankAgents())
  const [validation, setValidation] = useState<ValidationStates>(idleValidation())
  const [validateKeys, setValidateKeys] = useState(true)
  const [message, setMessage] = useState('')
  const [saving, setSaving] = useState(false)

  const loadStatus = (data: KeysStatus) => {
    setStatus(data)
    if (data.default) setDefaultConfig(fromStatus(data.default))
    setAgentConfigs((current) => {
      const next = { ...current }
      for (const { id } of AGENTS) {
        const saved = data.agents?.[id]
        next[id] = saved
          ? { enabled: saved.enabled, config: fromStatus(saved) }
          : { enabled: false, config: current[id].config }
      }
      return next
    })
  }

  useEffect(() => {
    void getKeysStatus().then(loadStatus).catch((error) => setMessage(handleApiError(error)))
  }, [])

  const markValidating = () => {
    const next = idleValidation()
    next.default = { state: 'validating', message: '正在校验…' }
    for (const { id } of AGENTS) {
      if (agentConfigs[id].enabled) next[id] = { state: 'validating', message: '正在校验…' }
    }
    setValidation(next)
  }

  const applyValidation = (result: SetupResponse, saved: boolean) => {
    const next = idleValidation()
    for (const configId of ['default', ...AGENTS.map(({ id }) => id)] as ConfigId[]) {
      const item = result.validation?.[configId]
      if (!item) continue
      next[configId] = item.ok
        ? { state: 'valid', message: saved ? '校验通过' : '校验通过，本次未保存' }
        : { state: 'invalid', message: item.error || '配置校验失败' }
    }
    setValidation(next)
  }

  const clearPlaintextKeys = () => {
    setDefaultConfig((value) => ({ ...value, api_key: '' }))
    setAgentConfigs((values) => {
      const next = { ...values }
      for (const { id } of AGENTS) {
        next[id] = { ...values[id], config: { ...values[id].config, api_key: '' } }
      }
      return next
    })
  }

  const save = async (event: React.FormEvent) => {
    event.preventDefault()
    if (saving) return
    setMessage('')
    const validationError = validateSetupForSave(defaultConfig, agentConfigs, status)
    if (validationError) {
      setMessage(validationError)
      return
    }
    setSaving(true)
    markValidating()
    try {
      const result = await saveSetup(buildSetupPayload(defaultConfig, agentConfigs, validateKeys))
      if (!result.saved) throw Object.assign(new Error(result.error || '模型配置未保存'), { body: result })
      applyValidation(result, true)
      const freshStatus = await getKeysStatus()
      loadStatus(freshStatus)
      clearPlaintextKeys()
      setMessage('模型配置已保存')
      if (standalone) window.location.assign(result.next || '/')
    } catch (error) {
      const response = (error as { body?: SetupResponse }).body
      if (response?.validation) applyValidation(response, false)
      setMessage(handleApiError(error))
    } finally {
      setSaving(false)
    }
  }

  const toggleAgent = (agentId: AgentId) => {
    setAgentConfigs((values) => {
      const current = values[agentId]
      const shouldSeed = !current.enabled && !current.config.provider && !current.config.base_url && !current.config.model
      return {
        ...values,
        [agentId]: {
          enabled: !current.enabled,
          config: shouldSeed ? { ...defaultConfig, api_key: '' } : current.config,
        },
      }
    })
    setValidation((values) => ({ ...values, [agentId]: { state: 'idle' } }))
  }

  const updateAgent = (agentId: AgentId, config: ModelConfigInput) => {
    setAgentConfigs((values) => ({ ...values, [agentId]: { ...values[agentId], config } }))
  }

  return <div className={standalone ? 'settings-standalone page-texture' : 'settings-overlay'}>
    <section className="settings-panel" aria-label="设置">
      <header><div><span className="eyebrow">SEC-GO SETTINGS</span><h1>设置</h1></div>{onClose && <button className="icon-button" onClick={onClose} aria-label="关闭设置"><Icon name="close" /></button>}</header>
      <div className="settings-layout"><nav aria-label="设置分类">
        <button className={section === 'general' ? 'active' : ''} onClick={() => setSection('general')}><Icon name="settings" />常规</button>
        <button className={section === 'models' ? 'active' : ''} onClick={() => setSection('models')}>◇ 模型配置</button>
        <button className={section === 'appearance' ? 'active' : ''} onClick={() => setSection('appearance')}>◐ 外观</button>
      </nav><form onSubmit={(event) => void save(event)}><div className="settings-content">
        {section === 'general' && <section className="settings-section"><h2>常规</h2><div className="settings-notice"><Icon name="user" /><div><strong>当前账户已受访问密码保护</strong><p>模型密钥只会提交到当前 SEC-GO 后端，浏览器不保存明文。</p></div></div></section>}
        {section === 'models' && <section className="settings-section model-settings-section">
          <h2>模型配置</h2><p>配置默认模型与 Agent 专用模型，关闭专用模型时自动复用默认模型。</p>
          <ModelFields title="默认模型（必填）" required value={defaultConfig} keyStatus={status?.default} validation={validation.default} onChange={setDefaultConfig} />
          <div className="agent-model-section"><h3>高级：Agent 专用模型（可选）</h3><p>为指定 Agent 使用独立模型；关闭时自动使用默认模型。</p>
            <div className="agent-override-list">{AGENTS.map((agent) => {
              const entry = agentConfigs[agent.id]
              return <article className={`agent-override-card ${entry.enabled ? 'enabled' : ''}`} key={agent.id}>
                <div className="switch-row"><span className="agent-identity"><strong>{agent.name}</strong><small>{agent.role} · {agent.description}</small><em>{entry.enabled ? '已单独指定模型' : '复用默认模型'}</em></span><button type="button" role="switch" aria-label={`${agent.name} 使用独立模型`} aria-checked={entry.enabled} className={`toggle-control ${entry.enabled ? 'enabled' : ''}`} onClick={() => toggleAgent(agent.id)}><span className="toggle-thumb" /></button></div>
                {entry.enabled && <ModelFields title={`${agent.name} 专用模型`} value={entry.config} keyStatus={status?.agents?.[agent.id]} validation={validation[agent.id]} onChange={(value) => updateAgent(agent.id, value)} />}
              </article>
            })}</div>
          </div>
        </section>}
        {section === 'appearance' && <section className="settings-section"><h2>外观</h2><div className="appearance-row"><span>主题</span><button type="button" onClick={onThemeToggle}>{theme === 'light' ? '浅色' : '深色'} · 点击切换</button></div></section>}
        {section === 'models' && <label className="check-row"><input type="checkbox" checked={validateKeys} onChange={(event) => setValidateKeys(event.target.checked)} />保存前校验所有已启用配置（新 API Key 始终校验）</label>}
        {message && <p className="settings-message">{message}</p>}
      </div><footer><button type="button" className="text-button danger" onClick={() => void logout().finally(() => window.location.assign('/login'))}>退出登录</button>{section === 'models' && <button className="primary-button" disabled={saving}>{saving ? '正在校验并保存…' : '保存设置'}</button>}</footer></form></div>
    </section>
  </div>
}

function ModelFields({ title, value, keyStatus, validation, required = false, onChange }: { title: string; value: ModelConfigInput; keyStatus?: ModelKeyStatus | null; validation: ValidationState; required?: boolean; onChange: (value: ModelConfigInput) => void }) {
  const providerListId = useId()
  const set = (field: keyof ModelConfigInput, next: string) => onChange({ ...value, [field]: next })
  return <div className="model-config-block"><fieldset><legend>{title}<span>{required ? '必填' : '独立配置'}</span></legend>
    <label>Provider<input role="combobox" aria-label={`${title} Provider`} list={providerListId} value={value.provider} onChange={(event) => set('provider', event.target.value)} required /><datalist id={providerListId}>{providerSuggestions.map((provider) => <option key={provider} value={provider} />)}</datalist></label>
    <label>Base URL<input value={value.base_url} onChange={(event) => set('base_url', event.target.value)} required /></label>
    <label>Model ID<input value={value.model} onChange={(event) => set('model', event.target.value)} required /></label>
    <label><span className="field-label-row"><span>API Key</span>{keyStatus?.has_key && <small className="key-mask">✓ 当前已配置 {keyStatus.api_key_masked}</small>}</span><input aria-label={`${title} API Key`} type="password" value={value.api_key ?? ''} onChange={(event) => set('api_key', event.target.value)} placeholder="输入新的 API Key" required={!keyStatus?.has_key} /><small className="field-hint">留空则继续使用当前已保存的 API Key；输入新 Key 将在校验成功后替换。</small></label>
  </fieldset><ValidationMessage value={validation} /></div>
}

function ValidationMessage({ value }: { value: ValidationState }) {
  if (value.state === 'idle') return null
  const prefix = value.state === 'valid' ? '✓' : value.state === 'invalid' ? '✕' : '…'
  return <p className={`model-validation ${value.state}`}>{prefix} {value.message}</p>
}
