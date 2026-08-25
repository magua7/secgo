# Flexible Model Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make default and Planner model configuration fully driven by arbitrary Provider, Base URL, Model ID, and API Key values stored in `settings.json`.

**Architecture:** Preserve the existing `coding` engine slot for the default model while storing its configured provider verbatim. Store an enabled Planner override in a semantic `planner` subscription, migrate the legacy `glm` slot on save, and route any non-Anthropic provider through the existing OpenAI-compatible client. The frontend uses a native editable combobox and never derives or resets sibling fields.

**Tech Stack:** FastAPI/Pydantic, Python dataclasses, React 19, TypeScript, Testing Library, Vitest, pytest.

---

### Task 1: Preserve arbitrary Provider values in backend configuration

**Files:**
- Modify: `secgo/web/server.py`
- Modify: `secgo/config/config.py`
- Test: `tests/test_web_model_settings.py`

- [ ] **Step 1: Write failing backend tests**

Add tests that call `_save_model_config()` with `provider: "siliconflow"`, then parse `settings.json` and assert both `llm.provider` and `subscriptions.coding.provider` equal `siliconflow`. Add a load test asserting `_apply_settings_json()` keeps the same provider while normalizing its OpenAI-compatible Base URL.

```python
def test_custom_provider_is_saved_verbatim(tmp_settings, monkeypatch):
    error, body = server._save_model_config(
        {"provider": "siliconflow", "base_url": "https://api.siliconflow.cn/v1", "model": "Qwen/Qwen3", "api_key": "secret"},
        None,
        False,
    )
    saved = parse_jsonc(tmp_settings.read_text(encoding="utf-8"))
    assert error is None and body == {"ok": True, "next": "/"}
    assert saved["llm"]["provider"] == "siliconflow"
    assert saved["subscriptions"]["coding"]["provider"] == "siliconflow"
```

- [ ] **Step 2: Run the focused backend tests and verify failure**

Run: `python -m pytest tests/test_web_model_settings.py -q`

Expected: FAIL because `_normalize_provider()` rewrites `siliconflow` to `openai` and config loading also discards it.

- [ ] **Step 3: Replace provider normalization with storage and protocol helpers**

In `secgo/web/server.py`, replace `_normalize_provider` with a storage helper that only trims input and defaults an empty value:

```python
def _clean_provider(provider: str) -> str:
    return (provider or "openai").strip() or "openai"
```

Use `_clean_provider()` when writing `llm` and subscription objects. In `secgo/config/config.py`, keep the provider string verbatim and call `_normalize_openai_base_url()` for every provider except exact case-insensitive `anthropic`.

- [ ] **Step 4: Run the focused backend tests and verify pass**

Run: `python -m pytest tests/test_web_model_settings.py -q`

Expected: all tests pass.

- [ ] **Step 5: Run the existing auth/config regression tests**

Run: `python -m pytest tests/test_web_auth.py tests/test_session_limit.py -q`

Expected: all tests pass.

### Task 2: Remove the fixed Planner `glm` subscription

**Files:**
- Modify: `secgo/web/server.py`
- Test: `tests/test_web_model_settings.py`

- [ ] **Step 1: Write failing Planner routing tests**

Add one test enabling a custom Planner and asserting `subscriptions.planner` plus `agents.planner.subscription == "planner"`. Seed a legacy `subscriptions.glm`/`agents.planner.subscription == "glm"` configuration and assert a subsequent save removes only the obsolete `glm` slot. Add a disabled-Planner test asserting the Planner agent and both `planner` and legacy `glm` overrides are removed so engine fallback uses `coding`.

- [ ] **Step 2: Run the Planner tests and verify failure**

Run: `python -m pytest tests/test_web_model_settings.py -q -k planner`

Expected: FAIL because the current implementation hard-codes `planner_sub_name = "glm"`.

- [ ] **Step 3: Write Planner configuration into the semantic slot**

Use `planner_sub_name = "planner"`; write the configured provider, URL, model, and key there; set `agents.planner.subscription` to `planner`; and remove legacy `glm` only when it is the old Planner override rather than an unrelated user subscription.

```python
planner_sub_name = "planner"
agents["planner"] = {
    "subscription": planner_sub_name,
    "modelId": planner_cfg["model"].strip(),
    "thinkingLevel": "medium",
}
```

- [ ] **Step 4: Run the Planner tests and verify pass**

Run: `python -m pytest tests/test_web_model_settings.py -q -k planner`

Expected: all selected tests pass.

- [ ] **Step 5: Verify key-status reads arbitrary current and legacy Planner slots**

Extend the API test to assert `/api/keys-status` reports the configured provider verbatim for `planner`, while still reading a legacy `glm` subscription before the next save.

### Task 3: Route arbitrary providers through supported protocols

**Files:**
- Modify: `secgo/model/provider.py`
- Modify: `secgo/web/server.py`
- Test: `tests/test_model_provider_routing.py`
- Test: `tests/test_web_model_settings.py`

- [ ] **Step 1: Write failing protocol-routing tests**

Patch `_stream_openai` and `_stream_anthropic`; assert `provider="siliconflow"` calls `_stream_openai`, mixed-case `Anthropic` calls `_stream_anthropic`, and local providers retain preset URL fallback.

- [ ] **Step 2: Run the routing tests and verify failure**

Run: `python -m pytest tests/test_model_provider_routing.py -q`

Expected: the mixed-case Anthropic test fails before normalization is centralized.

- [ ] **Step 3: Introduce one protocol classifier**

```python
def provider_protocol(provider: str) -> str:
    return "anthropic" if (provider or "").strip().lower() == "anthropic" else "openai"
```

Use it in streaming, summary generation, and setup validation. The stored provider remains unchanged; only dispatch uses the classifier.

- [ ] **Step 4: Make setup validation protocol-aware**

Pass provider into `_validate_subscription()`. Retain `/chat/completions` for OpenAI-compatible providers and use Anthropic's messages endpoint and headers for `anthropic`. Keep validation disabled behavior unchanged.

- [ ] **Step 5: Run routing and setup tests**

Run: `python -m pytest tests/test_model_provider_routing.py tests/test_web_model_settings.py -q`

Expected: all tests pass.

### Task 4: Implement editable Provider controls and standard Planner toggle

**Files:**
- Modify: `frontend/src/components/common/SettingsPanel.tsx`
- Modify: `frontend/src/styles/globals.css`
- Test: `frontend/src/components/common/SettingsPanel.test.tsx`

- [ ] **Step 1: Write failing component tests**

Cover these behaviors with Testing Library: type `siliconflow` into the Provider combobox; verify Base URL and Model ID remain unchanged; select a preset without implicit sibling reset; click Planner row text and assert the checkbox remains off; click the switch control and assert the Planner fieldset appears; verify the key mask is inside the API Key label row.

- [ ] **Step 2: Run the component test and verify failure**

Run: `npm --prefix frontend test -- --run src/components/common/SettingsPanel.test.tsx`

Expected: FAIL because Provider is a closed select and the whole Planner row toggles.

- [ ] **Step 3: Add a native editable combobox**

Render an `<input role="combobox" list="...">` backed by a `<datalist>` of presets. Bind its value directly to `ModelConfigInput.provider`; remove `blank(provider)` replacement behavior so Provider edits affect only Provider.

```tsx
<input
  role="combobox"
  aria-label={`${title} Provider`}
  list={listId}
  value={value.provider}
  onChange={(event) => set('provider', event.target.value)}
/>
<datalist id={listId}>{Object.keys(presets).map((name) => <option key={name} value={name} />)}</datalist>
```

- [ ] **Step 4: Add isolated switch markup and API-key label layout**

Use a non-label row plus a button or visually styled checkbox whose hit area is only the switch. Add `.field-label-row`, `.toggle-control`, `.toggle-track`, and `.toggle-thumb` styles without applying the generic 42px text-input rule to checkbox controls.

- [ ] **Step 5: Run SettingsPanel tests and typecheck**

Run: `npm --prefix frontend test -- --run src/components/common/SettingsPanel.test.tsx`

Run: `npm --prefix frontend run typecheck`

Expected: both commands pass.

### Task 5: Verify the complete model configuration slice

**Files:**
- Verify: `secgo/web/server.py`
- Verify: `secgo/config/config.py`
- Verify: `secgo/model/provider.py`
- Verify: `frontend/src/components/common/SettingsPanel.tsx`

- [ ] **Step 1: Run backend tests**

Run: `python -m pytest -q`

Expected: all backend tests pass.

- [ ] **Step 2: Run frontend tests and production checks**

Run: `npm --prefix frontend test -- --run`

Run: `npm --prefix frontend run typecheck`

Run: `npm --prefix frontend run build`

Expected: all commands pass and Vite produces the production bundle.
