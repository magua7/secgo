# Runtime Execution UX Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore persistent readable live narration, a real elapsed timer, reliable trace-panel navigation, and expanded stopped/error execution summaries without changing backend contracts or unrelated frontend areas.

**Architecture:** Keep SSE ingestion and the one-turn conversation architecture intact. Normalize already user-visible Agent stream text into typed per-turn narration records in the execution reducer, expose the latest four records through the existing presentation adapter, and render them as a fixed-height summary layer in `ExecutionBlock`. Drive elapsed display from a small frontend hook using `Date.now() - startedAt`, and route the trace action through a focused helper that opens the existing RightPanel trace tab while restoring conversation scroll position.

**Tech Stack:** React, TypeScript, Vitest, Testing Library, existing SEC-GO execution reducer and SSE client.

---

### Task 1: Persistent Live Narration State

**Files:**
- Modify: `frontend/src/types/execution.ts`
- Modify: `frontend/src/state/executionReducer.ts`
- Test: `frontend/src/state/executionReducer.test.ts`

- [ ] **Step 1: Write failing reducer tests**

Add tests proving non-Builder `llm:stream` text is retained as typed narration after later tool events, raw tool/system/handoff payloads are not promoted into narration, duplicate narration is merged, and stopped/error states retain narration and remain expanded.

- [ ] **Step 2: Run reducer tests and verify RED**

Run: `npm test -- --run src/state/executionReducer.test.ts`

Expected: assertions fail because narration is still `string[]`, live stream content is not persisted immediately, and stopped/error states collapse.

- [ ] **Step 3: Implement the minimal reducer change**

Define `NarrativeUpdate { id, text, agent, timestamp }`. Add safe readable-text normalization, append/update the active non-Builder narration entry during `llm:stream`/`engine:text`, keep raw tool output in evidence/timeline, and append only explicit short status narration for stop/error. Set `executionExpanded` true for stopped/error and preserve the last activity.

- [ ] **Step 4: Run reducer tests and verify GREEN**

Run: `npm test -- --run src/state/executionReducer.test.ts`

Expected: all reducer tests pass.

### Task 2: Execution Summary Information Layers

**Files:**
- Modify: `frontend/src/types/conversation.ts`
- Modify: `frontend/src/components/conversation/conversationAdapter.ts`
- Modify: `frontend/src/components/conversation/ExecutionBlock.tsx`
- Modify: `frontend/src/styles/globals.css`
- Test: `frontend/src/components/conversation/ExecutionBlock.test.tsx`

- [ ] **Step 1: Write failing component tests**

Add tests for the exact visible layers: one Current Activity, latest four Live Narration entries, latest eight deduplicated Key Progress entries, statistics, and the trace action. Verify older narration remains in presentation state but is not rendered, and stopped/error views are full summaries instead of thin rows.

- [ ] **Step 2: Run component tests and verify RED**

Run: `npm test -- --run src/components/conversation/ExecutionBlock.test.tsx`

Expected: no `过程播报` section exists and stopped/error render the old collapsed presentation.

- [ ] **Step 3: Implement the minimal presentation/UI change**

Pass typed narration through `executionToPresentation`, render only `slice(-4)`, render only `slice(-8)` Key Progress without nested log accordions, retain the existing statistics and trace link, and add scoped summary CSS only.

- [ ] **Step 4: Run component tests and verify GREEN**

Run: `npm test -- --run src/components/conversation/ExecutionBlock.test.tsx`

Expected: all ExecutionBlock tests pass.

### Task 3: Independent Elapsed Timer

**Files:**
- Create: `frontend/src/hooks/useElapsedTime.ts`
- Test: `frontend/src/hooks/useElapsedTime.test.tsx`
- Modify: `frontend/src/types/conversation.ts`
- Modify: `frontend/src/components/conversation/conversationAdapter.ts`
- Modify: `frontend/src/components/conversation/ExecutionBlock.tsx`

- [ ] **Step 1: Write a failing fake-timer test**

Render the hook with a stable `startedAt`, advance mocked system time without any SSE/reducer event, and assert elapsed advances from 69 to 70 seconds; then supply `endedAt`/non-running state and assert it freezes.

- [ ] **Step 2: Run timer test and verify RED**

Run: `npm test -- --run src/hooks/useElapsedTime.test.tsx`

Expected: module/behavior is absent.

- [ ] **Step 3: Implement Date.now-based timer hook**

Use an interval only to trigger React rendering every 250ms. Always calculate elapsed from `Date.now() - startedAt` while running and from `endedAt - startedAt` after completion, stop, or error.

- [ ] **Step 4: Run timer/component tests and verify GREEN**

Run: `npm test -- --run src/hooks/useElapsedTime.test.tsx src/components/conversation/ExecutionBlock.test.tsx`

Expected: timer advances independently and freezes at terminal time.

### Task 4: Trace Action Opens Existing RightPanel

**Files:**
- Create: `frontend/src/utils/traceAction.ts`
- Test: `frontend/src/utils/traceAction.test.ts`
- Modify: `frontend/src/pages/WorkspacePage.tsx`

- [ ] **Step 1: Write failing trace-action test**

Test that the action snapshots conversation `scrollTop`, sets RightPanel visible, selects the `trace` tab, and restores the same `scrollTop` on the next animation frame.

- [ ] **Step 2: Run trace-action test and verify RED**

Run: `npm test -- --run src/utils/traceAction.test.ts`

Expected: helper/behavior is absent.

- [ ] **Step 3: Implement and wire the action**

Call the helper from the existing `viewTrace` callback after selecting the exact live, committed, or historical trace. Do not introduce center accordions and do not alter normal RightPanel preference behavior.

- [ ] **Step 4: Run trace-action tests and verify GREEN**

Run: `npm test -- --run src/utils/traceAction.test.ts src/components/conversation/TurnView.test.tsx src/components/layout/RightPanel.test.tsx`

Expected: the explicit action opens trace without changing conversation position.

### Task 5: Full Verification

**Files:**
- Verify only; no additional feature changes.

- [ ] **Step 1: Run full frontend tests**

Run: `npm test -- --run`

Expected: all tests pass with zero failures.

- [ ] **Step 2: Run TypeScript validation**

Run: `npm run typecheck`

Expected: exit code 0.

- [ ] **Step 3: Build all frontend entries**

Run: `npm run build`

Expected: index, login, and setup builds complete successfully; only generated frontend static files change.

- [ ] **Step 4: Scope audit**

Confirm no Python/backend, API contract, SSE protocol, Home, Login, Settings, Sidebar, History grouping, Attachment, or theme-token source files were modified.
