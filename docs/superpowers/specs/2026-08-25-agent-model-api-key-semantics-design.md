# Agent Model API Key Semantics Design

## Scope

Upgrade only SEC-GO's model-settings frontend and the minimum Web Settings API needed to configure the Default model plus optional Planner, Research, Builder, and Operator overrides.

The implementation must not change Agent orchestration, routing, handoffs, SSE, tools, skills, sessions, history, authentication, workspace UI, homepage, login, or unrelated configuration.

The supplied image is a visual reference. Existing SEC-GO Settings styling remains authoritative, and unrelated styling is not redesigned.

## Existing Architecture

The runtime configuration layer already recognizes `planner`, `research`, `builder`, and `operator`. `_apply_settings_json()` binds any Agent without a usable explicit override to the `coding` subscription, which represents the Default model. Runtime Agent resolution reads these bindings without needing orchestration changes.

The current Web Settings slice is narrower:

- `_KeySetupReq`, `_save_model_config()`, and `/api/keys-status` expose only Default and Planner.
- The frontend API types, payload builder, validation, and `SettingsPanel` expose only Default and Planner.
- An empty API Key is currently rejected even when a securely stored key exists.
- Turning Planner off currently deletes its dedicated subscription and key.
- A successful save does not refresh the masked key until Settings is reopened.

## API Shape and Compatibility

The preferred request shape is:

```json
{
  "default": {
    "provider": "deepseek",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-chat",
    "api_key": "optional-new-plaintext-key"
  },
  "agents": {
    "planner": { "enabled": true, "config": {} },
    "research": { "enabled": false, "config": {} },
    "builder": { "enabled": false, "config": {} },
    "operator": { "enabled": false, "config": {} }
  },
  "validate_keys": true
}
```

`api_key` is omitted when the input is empty. The backend also accepts the existing `planner` field during a compatibility period and normalizes both representations into one internal structure. New frontend code sends the structured `agents` representation.

An Agent's `enabled` state is separate from whether a saved dedicated configuration exists. This distinction allows an override to be disabled without destroying it.

## Secure Key Resolution

For each submitted enabled configuration, the backend resolves the effective API Key as follows:

1. A non-empty new plaintext value is a replacement candidate.
2. An omitted or empty value reuses the corresponding key read directly from the current `settings.json` model subscription.
3. A Default model without a new or stored key fails required-field validation.
4. An enabled Agent override without a new or stored Agent-specific key fails required-field validation.
5. A disabled Agent does not require or validate an independent key.

Masked values are presentation data only. The frontend never copies a mask into an input or request. The backend rejects submitted key values containing mask markers such as `*`; it never treats a value like `sk-***9e` as a credential.

The backend does not use the loaded runtime fallback key to decide whether an Agent has a saved independent key. It reads the Agent's own persisted subscription so that inherited Default credentials cannot accidentally satisfy the Agent-specific requirement.

## Validation and Atomic Save

The backend builds a candidate settings document in memory without mutating the current file. It validates the Default model and every enabled Agent using each candidate's effective key. Reused stored keys are valid credentials for this validation; new candidates are not persisted before validation.

Validation returns a result for every active configuration rather than stopping at the first failure:

```json
{
  "ok": false,
  "saved": false,
  "validation": {
    "default": { "ok": true, "error": null },
    "planner": { "ok": true, "error": null },
    "research": { "ok": false, "error": "API Key 校验失败：HTTP 401" }
  },
  "error": "模型配置未保存，请检查 Research 配置"
}
```

Disabled overrides are represented as idle or omitted validation entries and are not reported as failures.

If any required field or enabled configuration fails, the backend does not write the candidate document. Previously saved models and keys remain unchanged, including a working key that a failed replacement attempted to supersede. Successful validations in a failed batch are described as validated but not saved.

Only after every enabled configuration passes does the backend merge and write all changes as one settings update, reset the loaded configuration, and return `saved: true`. Existing unrelated top-level keys and unrelated subscription or Agent entries are preserved.

## Persisted Override Semantics

Dedicated subscriptions use the semantic names `planner`, `research`, `builder`, and `operator`.

When an override is enabled, its Agent entry points at its same-named subscription. When disabled, its Agent binding is removed so runtime loading falls back to `coding`, but its dedicated subscription remains stored. Re-enabling the override can therefore restore its prior Provider, Base URL, Model ID, and API Key.

Legacy settings containing only Default or Default plus Planner continue to load. Missing Agent entries mean disabled overrides and use of the Default model. Existing legacy Planner handling remains readable until a successful save normalizes it where appropriate.

## Key Status Response

`/api/keys-status` returns status for Default and all four Agents. Each item contains only non-secret configuration and key metadata:

```json
{
  "enabled": true,
  "provider": "deepseek",
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-chat",
  "has_key": true,
  "api_key_masked": "sk-***9e"
}
```

For Agent entries, `enabled` reflects the persisted explicit Agent binding; an existing disabled dedicated subscription may still return its saved fields and masked key. The endpoint never returns a full key, and masks are generated only by the backend from the persisted source of truth.

## Frontend Structure and Behavior

The frontend defines one Agent metadata list and dictionary-based state keyed by `planner`, `research`, `builder`, and `operator`. It reuses a single model-fields component and a single Agent override item instead of duplicating JSX.

Each Agent row has an isolated Switch hit target. Disabled rows show the Agent identity, description, Default fallback status, and Switch. Enabled rows expand the shared two-column Provider, Base URL, Model ID, and API Key form.

The API Key label shows the saved state separately from the replacement input:

```text
API Key    ✓ 已配置 sk-***9e
[ 输入新的 API Key ]
留空则继续使用当前已保存的 API Key；输入新 Key 将在校验成功后替换。
```

Frontend required-field validation uses `has_key` from `/api/keys-status`. It requires a plaintext key only when Default or an enabled Agent has neither a new input nor an independently saved key.

Saving disables the global button and marks all active cards as validating. Structured backend results update each local status. A failed new key displays the old configured mask and the failed replacement message at the same time; the old status object is not replaced.

After a successful save, the frontend:

1. calls `/api/keys-status` again;
2. replaces status state with the fresh backend response;
3. displays the newly returned masks immediately;
4. clears every plaintext API Key input from React state; and
5. shows a compact global success message.

The frontend does not derive masks locally and does not automatically scroll on success.

## Testing

Backend tests cover:

- Default first-time key requirements and empty-input stored-key reuse;
- first-time Agent key requirements for every Agent;
- validation and successful replacement of each stored key;
- failed replacement preserving the previous file and key;
- rejection of masked-looking credentials;
- all-enabled validation with structured per-configuration results;
- zero persistence when any active configuration fails;
- disabling an override while preserving its subscription and key;
- re-enabling a preserved override without re-entering its key;
- Default fallback and real runtime resolution for all four Agents;
- backward compatibility with Default-only and legacy Planner settings; and
- preservation of unrelated settings.

Frontend tests cover:

- config-driven rendering of all four Agent switches;
- isolated Switch behavior and conditional expansion;
- required-key validation based on backend `has_key` state;
- empty inputs being omitted from payloads;
- old masks remaining visible beside replacement failures;
- structured local validation states and global atomic-save feedback;
- successful status refresh and plaintext clearing; and
- editable Provider controls retaining sibling field values.

Final verification runs focused tests during test-driven implementation, then the complete backend test suite, frontend test suite, TypeScript typecheck, and production build.

