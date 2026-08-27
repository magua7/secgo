import { useEffect, useState } from 'react'
import { getKeysStatus, handleApiError, saveVisionConfig, testVisionConfig } from '../../services/api'
import type { KeysStatus, SubscriptionOption, VisionCapabilityStatus, VisionConfigInput, VisionStatus, VisionTestRequest } from '../../types/api'
import { Icon } from './Icon'

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

const fromVisionStatus = (value: VisionStatus): VisionConfigInput => ({
  enabled: value.enabled,
  mode: value.mode,
  subscription: value.subscription,
  modelId: value.model_id,
  provider: value.provider || 'openai',
  baseURL: value.base_url,
  apiKey: '',
})

export function VisionSettings({ status, onMessage }: { status: KeysStatus | null; onMessage: (message: string) => void }) {
  const [visionConfig, setVisionConfig] = useState<VisionConfigInput>(blankVision())
  const [vision, setVision] = useState<VisionStatus | null>(null)
  const [visionTesting, setVisionTesting] = useState(false)
  const [visionKeyVisible, setVisionKeyVisible] = useState(false)
  const [visionTestResult, setVisionTestResult] = useState<{ status: 'verified' | 'failed'; message: string } | null>(null)

  const subscriptions: SubscriptionOption[] = status?.subscriptions ?? []

  const syncFromVision = (saved: VisionStatus | null) => {
    setVision(saved)
    setVisionConfig(saved ? fromVisionStatus(saved) : blankVision())
  }

  useEffect(() => {
    syncFromVision(status?.vision ?? null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status?.vision])

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
    if (!visionConfig.apiKey?.trim() && !vision?.has_api_key) return '请填写 API Key'
    return null
  }

  const visionDirty = Boolean(vision && (
    visionConfig.enabled !== vision.enabled
    || visionConfig.mode !== vision.mode
    || visionConfig.subscription !== vision.subscription
    || visionConfig.modelId !== vision.model_id
    || visionConfig.provider !== vision.provider
    || visionConfig.baseURL !== vision.base_url
  ))
  const visionStatus: VisionCapabilityStatus = vision?.status ?? 'unconfigured'
  const visionTestMessage = vision?.test_message ?? ''
  const visionBadgeText = (visionTestResult?.status === 'verified' && visionDirty)
    ? '测试通过 · 尚未保存'
    : VISION_STATUS_LABELS[visionStatus]
  const visionBadgeClass = (visionTestResult?.status === 'verified' && visionDirty) ? 'pending' : visionStatus

  const saveVision = async () => {
    onMessage('')
    const validationError = validateVisionForm()
    if (validationError) {
      onMessage(validationError)
      return
    }
    // 注意：保存只提交配置本身，不携带任何客户端测试结果；verified 只能由后端真实测试写入。
    const payload: VisionConfigInput = { ...visionConfig, apiKey: visionConfig.apiKey ?? '' }
    try {
      const result = await saveVisionConfig(payload)
      if (!result.saved) {
        onMessage(result.error || '视觉模型配置未保存')
        return
      }
      setVisionTestResult(null)
      try {
        const freshStatus = await getKeysStatus()
        syncFromVision(freshStatus.vision ?? null)
        onMessage('视觉模型配置已保存')
      } catch {
        onMessage('视觉模型配置已保存，但状态刷新失败')
      }
    } catch (error) {
      onMessage(handleApiError(error))
    }
  }

  const testVision = async () => {
    onMessage('')
    setVisionTesting(true)
    try {
      if (visionDirty) {
        // 测试表单当前值（临时，不落盘）
        const validationError = validateVisionForm()
        if (validationError) {
          onMessage(validationError)
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
        onMessage(result.status === 'verified'
          ? '视觉能力测试通过 · 尚未保存'
          : `视觉能力验证失败${result.message ? `：${result.message}` : ''}`)
      } else {
        // 测试已保存配置（后端持久化结果）
        const result = await testVisionConfig()
        try {
          const freshStatus = await getKeysStatus()
          syncFromVision(freshStatus.vision ?? null)
        } catch { /* 状态刷新失败不覆盖测试结果 */ }
        onMessage(result.status === 'verified'
          ? '视觉能力验证通过'
          : `视觉能力验证失败${result.message ? `：${result.message}` : ''}`)
      }
    } catch (error) {
      onMessage(handleApiError(error))
    } finally {
      setVisionTesting(false)
    }
  }

  const scrollToModelsTop = () => document.querySelector('.model-settings-section h2')?.scrollIntoView({ behavior: 'smooth', block: 'start' })

  return <div className="agent-model-section vision-section">
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
            <input aria-label="Vision API Key" type={visionKeyVisible ? 'text' : 'password'} value={visionConfig.apiKey ?? ''} onChange={(event) => updateVisionConfig({ apiKey: event.target.value })} placeholder={vision?.has_api_key ? '留空则保留当前已配置密钥' : '输入 API Key'} />
            <button type="button" className="icon-button" aria-label={visionKeyVisible ? '隐藏 API Key' : '显示 API Key'} onClick={() => setVisionKeyVisible((value) => !value)}><Icon name={visionKeyVisible ? 'eyeOff' : 'eye'} /></button>
          </span>
          <small className="field-hint">{vision?.has_api_key ? '已配置密钥；留空表示沿用当前密钥。' : '首次配置需填写 API Key。'}</small>
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
}
