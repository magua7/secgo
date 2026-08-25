# Agent Model API Key Semantics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional Planner, Research, Builder, and Operator model overrides with secure stored-key reuse, validated replacement, per-model feedback, and atomic all-or-nothing saving.

**Architecture:** Keep `coding` as the Default subscription and use same-named subscriptions for Agent overrides. The Web Settings backend resolves omitted keys from the persisted settings file, validates an in-memory candidate set, and writes only after every active configuration succeeds. The React UI uses dictionary state and reusable components, refreshes masks only from `/api/keys-status`, and never submits a masked value.

**Tech Stack:** Python 3.12, FastAPI/Pydantic, JSONC settings, pytest/unittest, React 19, TypeScript, Testing Library, Vitest, Vite.

---

## File Map

- `secgo/web/server.py`: normalize the new request, resolve persisted keys, validate all active configurations, atomically persist model settings, and return all model key statuses.
- `tests/test_web_model_settings.py`: backend regression tests for key reuse/replacement, four Agent overrides, structured validation, preservation, and compatibility.
- `tests/test_model_config_loading.py`: real configuration-resolution assertions proving enabled overrides and Default fallback.
- `frontend/src/types/api.ts`: shared Agent IDs, override payloads, key-status objects, and structured save responses.
- `frontend/src/services/api.ts`: clean payload construction, saved-key-aware client validation, and structured API errors.
- `frontend/src/services/api.test.ts`: payload and client-validation unit tests.
- `frontend/src/components/common/SettingsPanel.tsx`: config-driven model forms, switches, per-card validation status, key refresh, and plaintext clearing.
- `frontend/src/components/common/SettingsPanel.test.tsx`: UI behavior and save-flow tests.
- `frontend/src/styles/globals.css`: narrowly scoped Agent-card, key-state, and validation-state styling; preserve all existing unrelated edits in this already-dirty file.

### Task 1: Resolve stored keys without accepting masks

**Files:**
- Modify: `tests/test_web_model_settings.py`
- Modify: `secgo/web/server.py:441-550`

- [ ] **Step 1: Write failing tests for Default stored-key reuse and masked-value rejection**

Add tests that seed a real key, omit `api_key` from the submitted Default model, and assert the key survives. Add a second test that submits `sk-***9e` and asserts failure without a file change.

```python
def test_default_omitted_key_reuses_persisted_key(self) -> None:
    saved = self._save_request(
        initial=self._settings(default_key="stored-default"),
        default={"provider": "openai", "base_url": "https://new.example/v1", "model": "new-model"},
        agents={},
        validate_keys=False,
    )
    self.assertEqual(saved["llm"]["api_key"], "stored-default")
    self.assertEqual(saved["subscriptions"]["coding"]["apiKey"], "stored-default")

def test_masked_value_is_never_accepted_as_a_key(self) -> None:
    initial = self._settings(default_key="working-default")
    error, body, after = self._attempt_save(
        initial,
        default={"provider": "openai", "base_url": "https://api.example/v1", "model": "m", "api_key": "sk-***9e"},
        agents={},
        validate_keys=False,
    )
    self.assertIn("掩码", error)
    self.assertFalse(body["saved"])
    self.assertIn("掩码", body["validation"]["default"]["error"])
    self.assertEqual(after, initial)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest tests/test_web_model_settings.py -q -k "omitted_key or masked_value"`

Expected: both tests fail because `_check()` currently requires a submitted key and `_save_model_config()` has no structured Agent request.

- [ ] **Step 3: Add persisted-source helpers and extend the request model**

In `server.py`, define the supported IDs once and accept both new and legacy request fields:

```python
MODEL_AGENT_IDS = ("planner", "research", "builder", "operator")
MODEL_AGENT_LABELS = {
    "planner": "Planner", "research": "Research",
    "builder": "Builder", "operator": "Operator",
}

class _KeySetupReq(BaseModel):
    default: Optional[Dict[str, Any]] = None
    agents: Optional[Dict[str, Dict[str, Any]]] = None
    planner: Optional[Dict[str, Any]] = None
    validate_keys: bool = True
```

Add helpers that read only the persisted raw settings, never `get_config()` fallback data:

```python
def _submitted_key(cfg: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    value = str(cfg.get("api_key") or "").strip()
    if "*" in value:
        return None, "API Key 不能使用掩码值"
    return (value or None), None

def _stored_key(existing: Dict[str, Any], config_id: str) -> str:
    if config_id == "default":
        return str(((existing.get("subscriptions") or {}).get("coding") or {}).get("apiKey")
                   or (existing.get("llm") or {}).get("api_key") or "")
    return str(((existing.get("subscriptions") or {}).get(config_id) or {}).get("apiKey") or "")
```

Normalize `req.agents` into four `{enabled, config}` entries. When `agents` is absent, map the legacy `planner` value to its existing enabled/disabled meaning.

- [ ] **Step 4: Implement effective-key resolution before candidate construction**

Read `settings.json` before validation. For Default and each enabled Agent, use the new plaintext key when present and otherwise use `_stored_key()`. Return a required-key error only when both are empty. Store a boolean indicating whether each key is a replacement candidate.

```python
new_key, key_error = _submitted_key(cfg)
effective_key = new_key or _stored_key(existing, config_id)
if key_error:
    errors[config_id] = key_error
elif not effective_key:
    errors[config_id] = f"{label}：API Key 不能为空"
```

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run: `python -m pytest tests/test_web_model_settings.py -q -k "omitted_key or masked_value"`

Expected: 2 selected tests pass.

- [ ] **Step 6: Commit the isolated backend slice**

```bash
git add secgo/web/server.py tests/test_web_model_settings.py
git commit -m "fix: reuse securely stored model keys"
```

### Task 2: Validate and save all four overrides atomically

**Files:**
- Modify: `tests/test_web_model_settings.py`
- Modify: `secgo/web/server.py:454-550`

- [ ] **Step 1: Write failing tests for four-Agent persistence and atomic failure**

Add a parameterized test for every Agent ID, plus an all-enabled test where Research fails validation. Patch `_validate_subscription()` with a result selected by `model`.

```python
@pytest.mark.parametrize("agent_id", ("planner", "research", "builder", "operator"))
def test_enabled_agent_is_saved_in_semantic_subscription(agent_id, save_request):
    saved = save_request(default=DEFAULT, agents={
        agent_id: {"enabled": True, "config": model_input(agent_id, key=f"{agent_id}-key")}
    })
    assert saved["agents"][agent_id]["subscription"] == agent_id
    assert saved["subscriptions"][agent_id]["apiKey"] == f"{agent_id}-key"

def test_one_validation_failure_aborts_every_change(self) -> None:
    initial = self._settings(default_key="old-default", planner_key="old-planner")
    with patch.object(server, "_validate_subscription", side_effect=lambda provider, url, key, model:
                      (False, "HTTP 401") if model == "bad-research" else (True, "")):
        error, body, after = self._attempt_save(initial, NEW_DEFAULT, ALL_AGENTS, True)
    self.assertFalse(body["saved"])
    self.assertTrue(body["validation"]["default"]["ok"])
    self.assertFalse(body["validation"]["research"]["ok"])
    self.assertEqual(after, initial)
```

- [ ] **Step 2: Run the new tests and verify RED**

Run: `python -m pytest tests/test_web_model_settings.py -q -k "semantic_subscription or aborts_every_change"`

Expected: failures show that only Planner is supported and validation short-circuits with a global string.

- [ ] **Step 3: Build all candidates in memory and collect validation results**

Refactor `_save_model_config()` to accept `agents_cfg`, construct `validation` entries, and never write during validation. Always validate a newly submitted key; validate reused keys when `validate_keys` is true:

```python
should_validate = validate_keys or has_new_key
if should_validate and not field_error:
    ok, msg = _validate_subscription(provider, base_url, effective_key, model)
    validation[config_id] = {"ok": ok, "error": None if ok else _concise_validation_error(msg)}
else:
    validation[config_id] = {"ok": field_error is None, "error": field_error}
```

Continue through every enabled configuration even after a failure. If any active entry is invalid, return a response body with `ok: false`, `saved: false`, the complete `validation` map, and a concise global error. Do not call `write_text()` or `reset_config()`.

- [ ] **Step 4: Persist enabled and disabled overrides with preservation semantics**

For enabled Agents, write the same-named subscription using the effective key and bind `agents[agent_id]` to it with the existing thinking level. For disabled Agents, remove only the binding and retain an existing same-named subscription. If a legacy Planner binding points to `glm`, copy that subscription into `planner` before removing the binding so its saved key remains addressable.

```python
if request["enabled"]:
    subs[agent_id] = candidate_subscription
    agents[agent_id] = {
        "subscription": agent_id,
        "modelId": candidate_subscription["modelId"],
        "thinkingLevel": existing_thinking_or_default,
    }
else:
    agents.pop(agent_id, None)
```

Merge only `llm`, `subscriptions`, and `agents` into a copy of the existing document. Write after all validation passes and return `{"ok": True, "saved": True, "next": "/", "validation": validation}`.

- [ ] **Step 5: Update the endpoint to preserve structured failures**

Call the normalized save function from `api_setup_keys()`. Return the structured body with HTTP 400 when `saved` is false, rather than replacing it with a one-string response.

- [ ] **Step 6: Run backend model-settings tests and verify GREEN**

Run: `python -m pytest tests/test_web_model_settings.py -q`

Expected: all model-settings tests pass with no partial file writes.

- [ ] **Step 7: Commit the atomic multi-Agent backend**

```bash
git add secgo/web/server.py tests/test_web_model_settings.py
git commit -m "feat: save agent model overrides atomically"
```

### Task 3: Return complete masked status and verify real fallback

**Files:**
- Modify: `tests/test_web_model_settings.py`
- Modify: `tests/test_model_config_loading.py`
- Modify: `secgo/web/server.py:553-610`

- [ ] **Step 1: Write failing key-status tests**

Seed Default plus all four dedicated subscriptions, bind only Planner and Research, call `api_keys_status()`, and assert:

```python
assert body["default"]["has_key"] is True
assert body["default"]["api_key_masked"] == "def***key"
assert body["agents"]["planner"]["enabled"] is True
assert body["agents"]["research"]["enabled"] is True
assert body["agents"]["builder"]["enabled"] is False
assert body["agents"]["builder"]["has_key"] is True
assert "builder-key" not in response.body.decode()
assert "operator-key" not in response.body.decode()
```

- [ ] **Step 2: Run the status test and verify RED**

Run: `python -m pytest tests/test_web_model_settings.py -q -k keys_status`

Expected: failure because the endpoint exposes only `default` and `planner` and has no `has_key`/`enabled` fields.

- [ ] **Step 3: Rework `/api/keys-status` around persisted Agent ownership**

Generate the Default item from `coding`. For each Agent, locate its same-named saved subscription, with legacy Planner lookup only when the raw Planner binding identifies the legacy slot. Set `enabled` only when the raw Agent binding points to a usable non-`coding` subscription.

```python
def _status_item(sub, *, enabled: bool) -> Dict[str, Any]:
    key = str(sub.apiKey or "")
    return {
        "enabled": enabled,
        "provider": sub.provider,
        "base_url": sub.baseURL,
        "model": sub.modelId,
        "has_key": bool(key),
        "api_key_masked": mask(key),
    }
```

Return `agents` keyed by all four IDs. Keep existing top-level readiness/auth fields and legacy top-level Planner fields only if existing clients/tests require them.

- [ ] **Step 4: Add real configuration-resolution tests**

In `test_model_config_loading.py`, load a settings document where Planner and Research have explicit subscriptions and Builder/Operator do not. Assert:

```python
assert agents["planner"].subscription == "planner"
assert agents["research"].subscription == "research"
assert agents["builder"].subscription == "coding"
assert agents["operator"].subscription == "coding"
assert subscriptions[agents["planner"].subscription].modelId == "planner-model"
assert subscriptions[agents["research"].subscription].modelId == "research-model"
assert subscriptions[agents["builder"].subscription].modelId == "default-model"
```

- [ ] **Step 5: Run status and loading tests and verify GREEN**

Run: `python -m pytest tests/test_web_model_settings.py tests/test_model_config_loading.py -q`

Expected: both files pass, including legacy Default-only settings.

- [ ] **Step 6: Commit the status and fallback slice**

```bash
git add secgo/web/server.py tests/test_web_model_settings.py tests/test_model_config_loading.py
git commit -m "feat: expose masked status for all agent models"
```

### Task 4: Define frontend types, payloads, and structured errors

**Files:**
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/services/api.ts`
- Modify: `frontend/src/services/api.test.ts`

- [ ] **Step 1: Write failing service tests**

Add tests proving empty keys are omitted, enabled state is serialized for all Agents, saved-key-aware validation accepts an empty input, first-time enabled Agents require a key, and HTTP 400 structured validation survives in `ApiError`.

```typescript
it('allows an empty key when backend status confirms a stored key', () => {
  expect(validateSetupForSave(DEFAULT_INPUT, AGENT_INPUTS, STATUS_WITH_KEYS)).toBeNull()
})

it('requires a key for a first-time enabled Agent override', () => {
  const agents = { ...AGENT_INPUTS, research: { enabled: true, config: RESEARCH_WITHOUT_KEY } }
  expect(validateSetupForSave(DEFAULT_INPUT, agents, STATUS_WITHOUT_RESEARCH_KEY)).toContain('Research')
})

it('preserves structured validation details on an API error', async () => {
  vi.spyOn(window, 'fetch').mockResolvedValue(new Response(JSON.stringify({
    ok: false, saved: false, validation: { research: { ok: false, error: 'HTTP 401' } }, error: '未保存',
  }), { status: 400, headers: { 'Content-Type': 'application/json' } }))
  await expect(saveSetup(PAYLOAD)).rejects.toMatchObject({ body: { saved: false } })
})
```

- [ ] **Step 2: Run service tests and verify RED**

Run: `npm --prefix frontend test -- --run src/services/api.test.ts`

Expected: the new types/functions do not exist and current validation always requires plaintext keys.

- [ ] **Step 3: Add shared frontend model-setting types**

Define:

```typescript
export type AgentId = 'planner' | 'research' | 'builder' | 'operator'
export type ConfigId = 'default' | AgentId
export interface AgentOverrideInput { enabled: boolean; config: ModelConfigInput }
export type AgentOverrideInputs = Record<AgentId, AgentOverrideInput>
export interface ModelKeyStatus extends ModelConfig {
  enabled: boolean
  has_key: boolean
}
export interface KeysStatus {
  auth_enabled: boolean
  ready: boolean
  default: ModelKeyStatus | null
  agents: Record<AgentId, ModelKeyStatus | null>
}
export interface ValidationResult { ok: boolean; error: string | null }
export interface SetupResponse {
  ok: boolean
  saved: boolean
  next?: string
  error?: string
  validation: Partial<Record<ConfigId, ValidationResult>>
}
```

Update `SetupPayload` to carry `agents: AgentOverrideInputs`.

- [ ] **Step 4: Implement clean payload and saved-key-aware validation**

`buildSetupPayload()` trims fields and only includes `api_key` when the input contains non-whitespace plaintext. `validateSetupForSave()` checks Provider/Base URL/Model ID for Default and enabled overrides, then requires plaintext only when the matching status has no independently saved key.

```typescript
const hasUsableKey = (input: ModelConfigInput, status: ModelKeyStatus | null | undefined) =>
  Boolean(input.api_key?.trim()) || Boolean(status?.has_key)
```

- [ ] **Step 5: Preserve response bodies on API errors**

Extend `ApiError` with `body?: unknown`. Parse the response body once in `apiRequest()`, use its concise `error`/`detail` as the message, and attach the entire parsed object. Change `saveSetup()` to return `Promise<SetupResponse>`.

- [ ] **Step 6: Run service tests and verify GREEN**

Run: `npm --prefix frontend test -- --run src/services/api.test.ts`

Expected: all service tests pass. Full-project typechecking follows after the `SettingsPanel` call sites migrate in Task 5.

- [ ] **Step 7: Commit the frontend API contract**

```bash
git add frontend/src/types/api.ts frontend/src/services/api.ts frontend/src/services/api.test.ts
git commit -m "feat: define agent model settings contract"
```

### Task 5: Build the config-driven four-Agent Settings UI

**Files:**
- Modify: `frontend/src/components/common/SettingsPanel.test.tsx`
- Modify: `frontend/src/components/common/SettingsPanel.tsx`
- Modify: `frontend/src/styles/globals.css:55-70`

- [ ] **Step 1: Replace the narrow component mocks and add failing rendering tests**

Mock `/api/keys-status` with `default` plus an `agents` record. Assert four switches render, only the Switch toggles, disabled Agents show `复用默认模型`, and an enabled card displays its independently saved mask.

```typescript
for (const name of ['Planner', 'Research', 'Builder', 'Operator']) {
  expect(screen.getByRole('switch', { name: `${name} 使用独立模型` })).toBeInTheDocument()
}
expect(screen.getByText('高级：Agent 专用模型（可选）')).toBeInTheDocument()
```

- [ ] **Step 2: Add failing save-success and replacement-failure tests**

For success, enter a new Default key, click Save, resolve `saveSetup()`, then resolve a second `getKeysStatus()` response containing the new backend mask. Assert the second status call occurs, the new mask renders, and the password input is empty.

For failure, reject `saveSetup()` with an `ApiError` whose body contains a failed Research validation result. Assert the old saved mask remains and `新 API Key 校验失败：HTTP 401` appears.

- [ ] **Step 3: Run component tests and verify RED**

Run: `npm --prefix frontend test -- --run src/components/common/SettingsPanel.test.tsx`

Expected: failures show only Planner renders, save does not refresh status, and errors are global-only.

- [ ] **Step 4: Introduce config-driven state and reusable Agent rows**

Define a constant metadata array for the four Agents and initialize `Record<AgentId, AgentOverrideInput>` plus per-config validation state.

```typescript
const AGENTS = [
  { id: 'planner', name: 'Planner', role: '规划分析', description: '负责任务拆解、计划生成与执行路径规划。' },
  { id: 'research', name: 'Research', role: '信息检索', description: '负责网络搜索、信息检索与资料收集。' },
  { id: 'operator', name: 'Operator', role: '任务执行', description: '负责执行操作、调用工具与系统交互。' },
  { id: 'builder', name: 'Builder', role: '内容生成', description: '负责文案撰写、代码生成与内容创作。' },
] as const satisfies ReadonlyArray<{ id: AgentId; name: string; role: string; description: string }>
```

Load saved fields and `enabled` values from status without ever copying `api_key_masked` into `api_key`. Render the list through one `AgentOverrideItem` and reuse `ModelFields` for Default and Agent forms.

- [ ] **Step 5: Implement local validation states and secure key copy**

Show the stored status independently from the input:

```tsx
{keyStatus?.has_key && <small className="key-mask">✓ 当前已配置 {keyStatus.api_key_masked}</small>}
<input type="password" placeholder="输入新的 API Key" value={value.api_key ?? ''} />
<small className="field-hint">留空则继续使用当前已保存的 API Key；输入新 Key 将在校验成功后替换。</small>
```

Use `idle | validating | valid | invalid` state per active configuration. Map structured backend validation into local statuses. When a batch fails, successful entries say `校验通过，本次未保存`; failed entries show the concise replacement/configuration error. Preserve the current key-status state on failure.

- [ ] **Step 6: Refresh masks and clear plaintext only after success**

After `saveSetup()` returns `saved: true`, await `getKeysStatus()`, update status, then clear Default and every Agent `api_key` field. Do not clear on failure so the user can correct the attempted value.

```typescript
const freshStatus = await getKeysStatus()
setStatus(freshStatus)
setDefaultConfig((value) => ({ ...value, api_key: '' }))
setAgentConfigs((values) => mapAgentInputs(values, (entry) => ({
  ...entry, config: { ...entry.config, api_key: '' },
})))
```

- [ ] **Step 7: Add narrowly scoped styles**

Extend only model-settings selectors with compact Agent cards, expanded form spacing, neutral/validating/valid/invalid inline status colors, and the saved-key label row. Do not alter homepage, login, workspace, conversation, or general Settings selectors. Because `globals.css` already contains user changes, inspect its diff before and after and stage only the new model-settings hunks.

- [ ] **Step 8: Run component tests and typecheck and verify GREEN**

Run: `npm --prefix frontend test -- --run src/components/common/SettingsPanel.test.tsx`

Run: `npm --prefix frontend run typecheck`

Expected: all component tests pass and TypeScript reports zero errors.

- [ ] **Step 9: Commit without capturing unrelated CSS changes**

Stage `SettingsPanel.tsx` and its test normally. Stage only the model-settings CSS hunks using an index patch or interactive staging; confirm `git diff --cached --name-only` and `git diff --cached` before committing.

```bash
git commit -m "feat: configure models for all agents"
```

### Task 6: Full verification and scope audit

**Files:**
- Verify: all files above
- Do not modify: orchestration, SSE, tools, skills, sessions, history, login, homepage, or workspace code

- [ ] **Step 1: Run the complete backend suite**

Run: `python -m pytest -q`

Expected: all backend tests pass with zero failures.

- [ ] **Step 2: Run the complete frontend suite**

Run: `npm --prefix frontend test -- --run`

Expected: all Vitest tests pass with zero failures.

- [ ] **Step 3: Run static checks and production build**

Run: `npm --prefix frontend run typecheck`

Run: `npm --prefix frontend run build`

Expected: TypeScript exits 0 and all three Vite builds exit 0. The build may refresh existing generated static HTML; do not stage unrelated generated changes owned by the user.

- [ ] **Step 4: Audit the final diff and requirements**

Run: `git status --short`

Run: `git diff --check`

Run: `git diff --name-only`

Confirm only the scoped model-settings source/tests plus the pre-existing user-owned files appear. Inspect `git diff` to prove no secret or masked value is persisted as a credential and no unrelated configuration key is removed.

- [ ] **Step 5: Prepare the required final report**

Report the previous runtime fallback, previously Planner-only API structures, exact backend/frontend files changed, support for all four overrides, Default fallback, structured validation representation, atomic failure behavior, expanded key status, immediate mask refresh, plaintext clearing, backward compatibility, test/build evidence, and confirmation that orchestration/SSE/tools/skills were untouched.
