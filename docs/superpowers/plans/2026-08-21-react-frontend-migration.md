# SEC-GO React Frontend Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a self-contained React + Vite + TypeScript replacement for SEC-GO's three legacy pages with functional API/SSE parity and the approved Warm Intelligent Security UI.

**Architecture:** A three-entry Vite application produces self-contained `index.html`, `login.html`, and `setup.html` files in the existing FastAPI static directory. Typed HTTP/SSE adapters feed a reducer-driven conversation model shared by focused React components; no Python code changes.

**Tech Stack:** React 19, TypeScript, Vite, Vitest, React Testing Library, CSS variables, browser EventSource/fetch APIs, inline SVG icons.

---

### Task 1: Freeze legacy and establish the frontend toolchain

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/index.html`, `frontend/login.html`, `frontend/setup.html`
- Temporary migration archive (removed after React acceptance): `secgo/web/static/legacy/`

- [ ] Write a build-contract test that asserts all three source entries exist and the Vite output target is `secgo/web/static`.
- [ ] Run the test and confirm it fails because the frontend scaffold is absent.
- [ ] Add strict TypeScript, Vitest/jsdom, and a Vite post-build inlining plugin that removes emitted asset references from all three HTML files.
- [ ] Run the test and confirm it passes.

### Task 2: Implement typed contracts and reducer with TDD

**Files:**
- Create: `frontend/src/types/api.ts`, `events.ts`, `execution.ts`, `session.ts`
- Create: `frontend/src/state/executionReducer.ts`
- Test: `frontend/src/state/executionReducer.test.ts`

- [ ] Write failing tests for start, agent status, handoff, tool lifecycle, todo replacement, streaming report chunks, awaiting input, error/cancel/end terminal states, and automatic execution collapse.
- [ ] Run the focused reducer test and confirm the missing module failure.
- [ ] Implement discriminated event types, initial state, and the pure reducer without `any`.
- [ ] Run the focused test and confirm all reducer cases pass.

### Task 3: Implement API/SSE/session/theme adapters with TDD

**Files:**
- Create: `frontend/src/services/api.ts`, `sse.ts`
- Create: `frontend/src/hooks/useTheme.ts`, `usePanelPreference.ts`, `useAgentExecution.ts`
- Create: `frontend/src/utils/sessionGroups.ts`
- Test: matching `*.test.ts` files

- [ ] Write failing tests for credentials, 401/403 navigation targets, setup payload key omission, event-id deduplication, session date grouping, and stored theme/panel defaults.
- [ ] Run the focused tests and confirm expected missing exports.
- [ ] Implement the minimal adapters and hooks around browser APIs.
- [ ] Run focused tests and then the full suite.

### Task 4: Implement shared design system and branded primitives

**Files:**
- Create: `frontend/src/styles/tokens.css`, `globals.css`, `components.css`
- Create: `frontend/src/assets/secgo-logo.png`
- Create: `frontend/src/components/common/Brand.tsx`, `ThemeToggle.tsx`, `Icon.tsx`, `SettingsPanel.tsx`
- Test: `frontend/src/components/common/SettingsPanel.test.tsx`

- [ ] Write failing interaction tests for masked keys, omitted unchanged keys, validation state, and theme toggle.
- [ ] Implement shared primitives and the Settings form using only real setup endpoints.
- [ ] Add light/dark variables, typography, focus states, reduced-motion rules, and responsive breakpoints.
- [ ] Run component tests and TypeScript checking.

### Task 5: Implement Login and Home

**Files:**
- Create: `frontend/src/entries/login.tsx`, `home.tsx`, `setup.tsx`
- Create: `frontend/src/pages/LoginPage.tsx`, `HomePage.tsx`, `SettingsPage.tsx`
- Test: `frontend/src/pages/LoginPage.test.tsx`, `HomePage.test.tsx`

- [ ] Write failing tests for password-only login, left-pointing reveal beam state, quick-prompt fill, navigation, and task submission.
- [ ] Implement login behavior and the temporary reveal-dark state without changing stored theme.
- [ ] Implement the home prompt, six real prompt presets, and `/api/chat` handoff to `#/workspace`.
- [ ] Run page tests and the full suite.

### Task 6: Implement the conversation-first workspace

**Files:**
- Create: `frontend/src/pages/WorkspacePage.tsx`
- Create: `frontend/src/components/layout/AppShell.tsx`, `TopBar.tsx`, `Sidebar.tsx`, `RightPanel.tsx`
- Create: `frontend/src/components/conversation/ConversationFeed.tsx`, `UserMessage.tsx`, `AssistantMessage.tsx`, `ExecutionBlock.tsx`, `ReportView.tsx`, `Composer.tsx`
- Create: `frontend/src/components/execution/AgentProgress.tsx`, `ExecutionTimeline.tsx`, `EvidencePanel.tsx`, `ResourcePanel.tsx`, `TasksDock.tsx`
- Test: focused workspace/component tests

- [ ] Write failing tests for session selection, sessionStorage memory, new session, rename/delete, send/resume, stop, execution accordion, final report, sidebar modes, right-panel visibility, tabs, and completed tasks compaction.
- [ ] Implement the workspace with history grouped by date and no group-management UI.
- [ ] Connect the reducer to EventSource, preserve streaming and reconnect behavior, and close streams during session changes/unmount.
- [ ] Implement only local attachment display and prompt commands because no audited upload/command API exists.
- [ ] Run workspace tests, full suite, and type checking.

### Task 7: Build, deploy, and verify the frozen-backend integration

**Files:**
- Generate: `secgo/web/static/index.html`, `login.html`, `setup.html`
- Remove the temporary `secgo/web/static/legacy/` archive after React acceptance.

- [ ] Hash all `.py` files before deployment.
- [ ] Run `npm test -- --run`, `npm run typecheck`, and `npm run build` from `frontend`.
- [ ] Confirm each generated HTML is self-contained and has no `/assets/` dependency.
- [ ] Hash all `.py` files after deployment and compare for exact equality.
- [ ] Start the existing FastAPI web command for a smoke check of `/`, `/login`, `/setup`, and generated assets.
- [ ] Inspect generated output for `.env`, known configuration keys, or secret-like literal leakage and report any backend-only limitations.
