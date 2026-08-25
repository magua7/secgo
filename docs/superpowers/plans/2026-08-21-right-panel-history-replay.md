# Right Panel and History Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the right execution panel under user control and present live, direct-response, empty, and historical Agent states without fabricated metadata or unbounded raw output.

**Architecture:** Treat `secgo.rightPanel` as the sole source of panel visibility and remove conversation-driven visibility writes. Keep trace selection separate from visibility. Normalize saved history into a read-only view model with optional statistics, bounded raw text, and one reusable empty-state component.

**Tech Stack:** React 19, TypeScript, Vitest, Testing Library, CSS.

---

### Task 1: Decouple panel visibility from conversation state

**Files:**
- Modify: `frontend/src/pages/WorkspacePage.tsx`
- Test: `frontend/src/pages/WorkspacePage.test.tsx`
- Verify: `frontend/src/hooks/preferences.ts`

- [ ] **Step 1: Write failing visibility tests**

Render the workspace with default preferences and assert the panel is visible. Simulate new task, send, direct completion, Agent start, session selection, and history load; assert none changes visibility. Click the right edge handle and assert visibility changes and persists as `secgo.rightPanel=hidden` or `expanded`.

- [ ] **Step 2: Run the focused workspace tests and verify failure**

Run: `npm --prefix frontend test -- --run src/pages/WorkspacePage.test.tsx`

Expected: FAIL because `WorkspacePage` calls `setRightVisible()` from effects and session actions.

- [ ] **Step 3: Remove all non-handle visibility writes**

Delete `manualRightPanelRef`, `previousLiveKindRef`, and the live-kind visibility effect. Remove `setRightVisible(false/true)` from `select`, `create`, `send`, and `viewTrace`. Keep only:

```ts
const toggleRightPanel = () => setRightVisible(!rightVisible)
```

`viewTrace()` may set `selectedTrace` and `rightTab`, but not visibility.

- [ ] **Step 4: Run workspace tests and verify pass**

Run: `npm --prefix frontend test -- --run src/pages/WorkspacePage.test.tsx`

Expected: all selected tests pass.

### Task 2: Model unknown history metadata honestly

**Files:**
- Modify: `frontend/src/types/conversation.ts`
- Modify: `frontend/src/types/executionTrace.ts`
- Modify: `frontend/src/components/conversation/conversationAdapter.ts`
- Modify: `frontend/src/components/layout/executionTraceAdapter.ts`
- Test: `frontend/src/components/conversation/conversationAdapter.test.ts`
- Test: `frontend/src/components/layout/executionTraceAdapter.test.ts`

- [ ] **Step 1: Write failing adapter tests**

Assert historical Agent turns use `evidenceCount: null`, no synthetic timestamp, and no completed status. Assert direct history contains no trace. Assert fallback user-role tool/system messages remain internal execution records rather than separate user turns.

- [ ] **Step 2: Run adapter tests and verify failure**

Run: `npm --prefix frontend test -- --run src/components/conversation/conversationAdapter.test.ts src/components/layout/executionTraceAdapter.test.ts`

Expected: FAIL because history currently hard-codes zero evidence and exposes some persisted system prompts as user turns.

- [ ] **Step 3: Make unknown counts optional and classify persisted system hints**

Change historical `evidenceCount` to `number | null`; omit it from summaries when null. Extend `historyMessageSemantic()` to recognize persisted `[系统提示：...]` records as system execution metadata. Keep live counts numeric.

- [ ] **Step 4: Run adapter tests and verify pass**

Run: `npm --prefix frontend test -- --run src/components/conversation/conversationAdapter.test.ts src/components/layout/executionTraceAdapter.test.ts`

Expected: all selected tests pass.

### Task 3: Normalize and bound historical raw output

**Files:**
- Create: `frontend/src/components/layout/historyTraceText.ts`
- Create: `frontend/src/components/layout/historyTraceText.test.ts`
- Modify: `frontend/src/components/layout/executionTraceAdapter.ts`
- Modify: `frontend/src/components/layout/RightPanel.tsx`
- Modify: `frontend/src/styles/globals.css`

- [ ] **Step 1: Write failing text normalization tests**

Test plain text, JSON wrappers such as `{"success":true,"output":"line1\\nline2"}`, nested stringified JSON, malformed JSON, and HTML-like text. Assert controlled newline restoration, no exception, and unchanged literal markup.

- [ ] **Step 2: Run the normalizer tests and verify failure**

Run: `npm --prefix frontend test -- --run src/components/layout/historyTraceText.test.ts`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement safe iterative normalization**

Create `normalizeHistoryTraceText(value: string)` that attempts at most two JSON parses, extracts string `output`/`result` values, converts escaped CRLF/newline sequences only in the extracted/plain text, and returns text for React rendering. Never use `dangerouslySetInnerHTML`.

- [ ] **Step 4: Render historical details in collapsible bounded blocks**

For `history-readonly`, render each detail inside `<details className="history-trace-raw">` with a `<pre>`. Style the pre with `max-height:260px`, `overflow:auto`, `white-space:pre-wrap`, and `overflow-wrap:anywhere`. Keep live timeline rendering unchanged.

- [ ] **Step 5: Run normalizer and adapter tests**

Run: `npm --prefix frontend test -- --run src/components/layout/historyTraceText.test.ts src/components/layout/executionTraceAdapter.test.ts`

Expected: all selected tests pass.

### Task 4: Unify right-panel empty states

**Files:**
- Create: `frontend/src/components/layout/PanelEmptyState.tsx`
- Modify: `frontend/src/components/layout/RightPanel.tsx`
- Modify: `frontend/src/styles/globals.css`
- Test: `frontend/src/components/layout/RightPanel.test.tsx`

- [ ] **Step 1: Write failing empty-state tests**

Cover new session/direct reply text, empty live Agent trace, missing historical trace, unknown evidence, and missing resources. Assert the same `data-testid="panel-empty-state"` component is used and no unknown count is rendered as zero.

- [ ] **Step 2: Run the focused RightPanel tests and verify failure**

Run: `npm --prefix frontend test -- --run src/components/layout/RightPanel.test.tsx`

Expected: FAIL because `RightPanel` uses a private text-only `Empty` function.

- [ ] **Step 3: Add and use `PanelEmptyState`**

```tsx
export function PanelEmptyState({ title, description }: { title: string; description?: string }) {
  return <div className="panel-empty" data-testid="panel-empty-state">
    <span aria-hidden="true">◇</span><strong>{title}</strong>{description && <p>{description}</p>}
  </div>
}
```

Replace all trace/evidence/resource/direct empty branches with this component and add restrained typography/spacing styles.

- [ ] **Step 4: Run RightPanel tests and typecheck**

Run: `npm --prefix frontend test -- --run src/components/layout/RightPanel.test.tsx`

Run: `npm --prefix frontend run typecheck`

Expected: both commands pass.

### Task 5: Verify the complete execution-panel slice

**Files:**
- Verify: `frontend/src/pages/WorkspacePage.tsx`
- Verify: `frontend/src/components/layout/RightPanel.tsx`
- Verify: `frontend/src/components/layout/executionTraceAdapter.ts`

- [ ] **Step 1: Run all frontend tests**

Run: `npm --prefix frontend test -- --run`

Expected: all frontend tests pass.

- [ ] **Step 2: Run typecheck and production build**

Run: `npm --prefix frontend run typecheck`

Run: `npm --prefix frontend run build`

Expected: both commands pass.

- [ ] **Step 3: Inspect forbidden coupling**

Search `WorkspacePage.tsx` and verify `setRightVisible` appears only in the edge-handle toggle. Search for `dangerouslySetInnerHTML` in the new history path and verify it is absent.
