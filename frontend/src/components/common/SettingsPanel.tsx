import { useEffect, useId, useState } from 'react'
import { buildSetupPayload, getKeysStatus, handleApiError, logout, saveSetup, saveVisionConfig, testVisionConfig, validateSetupForSave } from '../../services/api'
import type { AgentId, AgentOverrideInputs, ConfigId, KeysStatus, ModelConfigInput, ModelKeyStatus, SetupResponse, SubscriptionOption, VisionCapabilityStatus, VisionConfigInput, VisionMode, VisionTestRequest } from '../../types/api'
import { Icon } from './Icon'
import { McpStatusPanel } from './McpStatusPanel'
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

type SettingsSection = 'general' | 'models' | 'appearance' | 'tools'
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

const VISION_STATUS_LABELS: Record<VisionCapabilityStatus, string> = {
  unconfigured: '未配置',
  pending: '待验证',
  verified: '可用',
  failed: '不可用',
}

// Vision 自定义模式的 Provider 选项（沿用项目已有类型：OpenAI Compatible / Anthropic）
const VISION_PROVIDERS: ReadonlyArray<{ value: string; label: string }> = [
  { value: 'openai', label: 'OpenAI Compatible' },
  { value: 'anthropic', label: 'Anthropic' },
]

const blankVision = (): VisionConfigInput => ({
  enabled: false, mode: 'reuse', subscription: '', modelId: '', provider: 'openai', baseURL: '', apiKey: '',
})

export function SettingsPanel({ standalone = false, onClose, theme = 'light', onThemeToggle }: { standalone?: boolean; onClose?: () => void; theme?: Theme; onThemeToggle?: () => void }) {
  const [section, setSection] = useState<SettingsSection>('models')
  const [status, setStatus] = useState<KeysStatus | null>(null)
  const [defaultConfig, setDefaultConfig] = useState<ModelConfigInput>(blank())
  const [agentConfigs, setAgentConfigs] = useState<AgentOverrideInputs>(blankAgents())
  const [visionConfig, setVisionConfig] = useState<VisionConfigInput>(blankVision())
  const [subscriptions, setSubscriptions] = useState<SubscriptionOption[]>([])
  const [visionTesting, setVisionTesting] = useState(false)
  const [visionKeyVisible, setVisionKeyVisible] = useState(false)
  const [visionTestResult, setVisionTestResult] = useState<{ status: 'verified' | 'failed'; message: string } | null>(null)
  const [validation, setValidation] = useState<ValidationStates>(idleValidation())
  const [validateKeys, setValidateKeys] = useState(true)
  const [message, setMessage] = useState('')
  const [saving, setSaving] = useState(false)

  const loadStatus = (data: KeysStatus) => {
    setStatus(data)
    if (data.default) setDefaultConfig(fromStatus(data.default))
    setSubscriptions(data.subscriptions ?? [])
    setVisionConfig(data.vision
      ? {
          enabled: data.vision.enabled,
          mode: data.vision.mode,
          subscription: data.vision.subscription,
          modelId: data.vision.model_id,
          provider: data.vision.provider || 'openai',
          baseURL: data.vision.base_url,
          apiKey: '',
        }
      : blankVision())
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
      clearPlaintextKeys()
      try {
        const freshStatus = await getKeysStatus()
        loadStatus(freshStatus)
        setMessage('模型配置已保存')
      } catch (refreshError) {
        setMessage(`模型配置已保存，但状态刷新失败：${handleApiError(refreshError)}`)
      }
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

  const updateVisionConfig = (patch: Partial<VisionConfigInput>) => {
    setVisionConfig((value) => ({ ...value, ...patch }))
    setVisionTestResult(null)
  }

  const validateVisionForm = (): string | null => {
    if (!visionConfig.enabled) return null
    if (visionConfig.mode === 'reuse') {
      if (!visionConfig.subscription.trim() || !visionConfig.modelId.trim()) return '请选择模型订阅并填写视觉模型'
      return null
    }
    if (!visionConfig.baseURL.trim() || !visionConfig.modelId.trim()) return '请填写 Base URL 与视觉模型'
    if (!visionConfig.apiKey?.trim() && !status?.vision?.has_api_key) return '请填写 API Key'
    return null
  }

  const savedVision = status?.vision
  const visionDirty = Boolean(savedVision && (
    visionConfig.enabled !== savedVision.enabled
    || visionConfig.mode !== savedVision.mode
    || visionConfig.subscription !== savedVision.subscription
    || visionConfig.modelId !== savedVision.model_id
    || visionConfig.provider !== savedVision.provider
    || visionConfig.baseURL !== savedVision.base_url
  ))
  const visionStatus: VisionCapabilityStatus = status?.vision?.status ?? 'unconfigured'
  const visionTestMessage = status?.vision?.test_message ?? ''
  const visionBadgeText = (visionTestResult?.status === 'verified' && visionDirty)
    ? '测试通过 · 尚未保存'
    : VISION_STATUS_LABELS[visionStatus]
  const visionBadgeClass = (visionTestResult?.status === 'verified' && visionDirty) ? 'pending' : visionStatus

  const saveVision = async () => {
    setMessage('')
    const validationError = validateVisionForm()
    if (validationError) {
      setMessage(validationError)
      return
    }
    // 注意：保存只提交配置本身，不携带任何客户端测试结果；verified 只能由后端真实测试写入。
    const payload: VisionConfigInput = { ...visionConfig, apiKey: visionConfig.apiKey ?? '' }
    try {
      const result = await saveVisionConfig(payload)
      if (!result.saved) {
        setMessage(result.error || '视觉模型配置未保存')
        return
      }
      setVisionTestResult(null)
      try {
        const freshStatus = await getKeysStatus()
        loadStatus(freshStatus)
        setMessage('视觉模型配置已保存')
      } catch {
        setMessage('视觉模型配置已保存，但状态刷新失败')
      }
    } catch (error) {
      setMessage(handleApiError(error))
    }
  }

  const testVision = async () => {
    setMessage('')
    setVisionTesting(true)
    try {
      if (visionDirty) {
        // 测试表单当前值（临时，不落盘）
        const validationError = validateVisionForm()
        if (validationError) {
          setMessage(validationError)
          return
        }
        const payload: VisionTestRequest = {
          mode: visionConfig.mode,
          subscription: visionConfig.subscription,
          modelId: visionConfig.modelId,
          provider: visionConfig.provider,
          baseURL: visionConfig.baseURL,
          apiKey: visionConfig.apiKey ?? '',
        }
        const result = await testVisionConfig(payload)
        if (result.status === 'verified' || result.status === 'failed') {
          setVisionTestResult({ status: result.status, message: result.message ?? '' })
        }
        setMessage(result.status === 'verified'
          ? '视觉能力测试通过 · 尚未保存'
          : `视觉能力验证失败${result.message ? `：${result.message}` : ''}`)
      } else {
        // 测试已保存配置（后端持久化结果）
        const result = await testVisionConfig()
        try {
          const freshStatus = await getKeysStatus()
          loadStatus(freshStatus)
        } catch { /* 状态刷新失败不覆盖测试结果 */ }
        setMessage(result.status === 'verified'
          ? '视觉能力验证通过'
          : `视觉能力验证失败${result.message ? `：${result.message}` : ''}`)
      }
    } catch (error) {
      setMessage(handleApiError(error))
    } finally {
      setVisionTesting(false)
    }
  }

  const scrollToModelsTop = () => document.querySelector('.model-settings-section h2')?.scrollIntoView({ behavior: 'smooth', block: 'start' })

  return <div className={standalone ? 'settings-standalone page-texture' : 'settings-overlay'}>
    <section className="settings-panel" aria-label="设置">
      <header><div><span className="eyebrow">SEC-GO SETTINGS</span><h1>设置</h1></div>{onClose && <button className="icon-button" onClick={onClose} aria-label="关闭设置"><Icon name="close" /></button>}</header>
      <div className="settings-layout"><nav aria-label="设置分类">
        <button className={section === 'general' ? 'active' : ''} onClick={() => setSection('general')}><Icon name="settings" />常规</button>
        <button className={section === 'models' ? 'active' : ''} onClick={() => setSection('models')}>◇ 模型配置</button>
        <button className={section === 'appearance' ? 'active' : ''} onClick={() => setSection('appearance')}>◐ 外观</button>
        <button className={section === 'tools' ? 'active' : ''} onClick={() => setSection('tools')}><Icon name="tool" />工具 / MCP</button>
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
          <div className="agent-model-section vision-section">
            <div className="switch-row"><span className="agent-identity"><strong>图片视觉分析</strong><small>使用视觉模型理解截图、页面和图像中的安全线索。</small></span><button type="button" role="switch" aria-label="启用图片视觉分析" aria-checked={visionConfig.enabled} className={`toggle-control ${visionConfig.enabled ? 'enabled' : ''}`} onClick={() => updateVisionConfig({ enabled: !visionConfig.enabled })}><span className="toggle-thumb" /></button></div>
            {visionConfig.enabled && <div className="vision-config">
              <div className="vision-status-row"><span>视觉模型</span><span className={`vision-status ${visionBadgeClass}`}>● {visionBadgeText}</span></div>

              <div className="vision-mode-toggle" role="radiogroup" aria-label="配置方式">
                <button type="button" role="radio" aria-checked={visionConfig.mode === 'reuse'} className={`vision-mode-option ${visionConfig.mode === 'reuse' ? 'active' : ''}`} onClick={() => updateVisionConfig({ mode: 'reuse' })}>复用已有订阅</button>
                <button type="button" role="radio" aria-checked={visionConfig.mode === 'custom'} className={`vision-mode-option ${visionConfig.mode === 'custom' ? 'active' : ''}`} onClick={() => updateVisionConfig({ mode: 'custom' })}>自定义模型</button>
              </div>

              {visionConfig.mode === 'reuse' && <>
                <label>模型订阅
                  {subscriptions.length > 0
                    ? <select aria-label="模型订阅" value={visionConfig.subscription} onChange={(event) => updateVisionConfig({ subscription: event.target.value })}><option value="">选择订阅…</option>{subscriptions.map((sub) => <option key={sub.name} value={sub.name}>{sub.name} · {sub.provider} · {sub.model}</option>)}</select>
                    : <div className="vision-empty"><p>暂无已配置的模型订阅，请先在「默认模型」或「Agent 专用模型」中添加。</p><button type="button" className="text-button" onClick={scrollToModelsTop}>添加模型订阅</button></div>}
                  <small className="field-hint">选择已配置的模型服务。</small>
                </label>
                <label>视觉模型
                  <input value={visionConfig.modelId} onChange={(event) => updateVisionConfig({ modelId: event.target.value })} placeholder="如 qwen-vl-max" />
                  <small className="field-hint">指定用于图片理解的模型（必填）。</small>
                </label>
              </>}

              {visionConfig.mode === 'custom' && <>
                <label>Provider
                  <select aria-label="Vision Provider" value={visionConfig.provider} onChange={(event) => updateVisionConfig({ provider: event.target.value })}>{VISION_PROVIDERS.map((provider) => <option key={provider.value} value={provider.value}>{provider.label}</option>)}</select>
                </label>
                <label>Base URL
                  <input aria-label="Vision Base URL" value={visionConfig.baseURL} onChange={(event) => updateVisionConfig({ baseURL: event.target.value })} placeholder="https://api.example.com/v1" />
                </label>
                <label>Model ID
                  <input aria-label="Vision Model ID" value={visionConfig.modelId} onChange={(event) => updateVisionConfig({ modelId: event.target.value })} placeholder="如 qwen-vl-max / gpt-4o" />
                </label>
                <label>API Key
                  <span className="vision-key-row">
                    <input aria-label="Vision API Key" type={visionKeyVisible ? 'text' : 'password'} value={visionConfig.apiKey ?? ''} onChange={(event) => updateVisionConfig({ apiKey: event.target.value })} placeholder={status?.vision?.has_api_key ? '留空则保留当前已配置密钥' : '输入 API Key'} />
                    <button type="button" className="icon-button" aria-label={visionKeyVisible ? '隐藏 API Key' : '显示 API Key'} onClick={() => setVisionKeyVisible((value) => !value)}><Icon name={visionKeyVisible ? 'eyeOff' : 'eye'} /></button>
                  </span>
                  <small className="field-hint">{status?.vision?.has_api_key ? '已配置密钥；留空表示沿用当前密钥。' : '首次配置需填写 API Key。'}</small>
                </label>
              </>}

              {visionStatus === 'failed' && visionTestMessage && <p className="vision-test-error">上次检测失败：{visionTestMessage}</p>}
              <div className="vision-actions">
                <button type="button" className="secondary-button" disabled={visionTesting} onClick={() => void testVision()}>{visionTesting ? '正在测试…' : '测试视觉能力'}</button>
                <button type="button" className="primary-button" onClick={() => void saveVision()}>保存配置</button>
              </div>
              <p className="field-hint">Vision 使用所选订阅或自定义服务的连接信息与 API Key。</p>
            </div>}
          </div>
        </section>}
        {section === 'appearance' && <section className="settings-section"><h2>外观</h2><div className="appearance-row"><span>主题</span><button type="button" onClick={onThemeToggle}>{theme === 'light' ? '浅色' : '深色'} · 点击切换</button></div></section>}
        {section === 'tools' && <McpStatusPanel />}
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