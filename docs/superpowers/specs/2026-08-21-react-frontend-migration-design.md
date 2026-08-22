# SEC-GO React Frontend Migration Design

## Goal and non-negotiable constraints

Replace the three legacy HTML/CSS/JavaScript pages with a React + Vite + TypeScript frontend while treating `secgo/web/server.py` and every other Python file as frozen. The frontend must preserve the live API, authentication, SSE, session, cancellation, streaming, and model-setting contracts. The group-management feature remains available in the frozen backend but is intentionally absent from the new UI.

The supplied logo and six UI references define a shared “Warm Intelligent Security” visual language. They are not literal copy sources. Product wording and behavior come from the source contract and the user specification.

## Existing frontend contract audit

### Static serving

FastAPI returns three exact files and does not mount a static asset directory:

- `/` returns `login.html`, `setup.html`, or `index.html` according to cookie authentication and model readiness.
- `/login` returns `login.html` or redirects an authenticated user.
- `/setup` returns `setup.html` to authenticated users.

The Vite output must therefore be self-contained HTML. The build has three entries and inlines each entry's JavaScript and CSS into the corresponding page. No FastAPI route or static mount changes are allowed.

### Authentication and settings

- `POST /api/login`: `multipart/form-data` with `password`; returns `{ok,next}` or `{ok:false,error}`.
- `POST /api/logout`: clears the HttpOnly auth cookie.
- `GET /api/keys-status`: returns readiness plus masked default/planner model configuration; never returns a plain key.
- `POST /api/setup-keys`: accepts `{default, planner, validate_keys}`. Existing masked keys are preserved by omitting `api_key` when the input stays empty.
- HTTP 401 routes the UI to `/login`; HTTP 403 routes it to `/setup`.

The old setup step is folded into a normal Settings experience, but the standalone `setup.html` entry renders the same settings component because the frozen server redirects an authenticated, unconfigured user there.

### Sessions and conversation

- `GET /api/sessions` returns `{sessions,groups}`; the frontend uses only `sessions` and groups them by time as Today, Yesterday, Earlier.
- `GET /api/sessions/{id}/messages` returns rendered `{kind,text}` messages and `todoList`.
- `POST /api/chat` accepts `{message,sessionId?}` and returns `{sessionId,accepted,resumed}`.
- `POST /api/sessions/{id}/cancel` cancels an active task.
- `PUT /api/sessions/{id}/title` and `DELETE /api/sessions/{id}` preserve rename/delete behavior.
- Current session id remains in `sessionStorage` so tabs are isolated while refresh retains the active conversation.

Attachments and slash-command controls are rendered as discoverable affordances. The audited backend has no upload endpoint, so attachment selection is kept local and clearly shown as “not sent”; slash-command presets fill the composer instead of inventing an API.

### SSE contract

`GET /api/events?sessionId=...` is an EventSource stream with numeric event ids and browser-native reconnect. Registered events are:

`engine:start`, `agent:thinking`, `agent:switch`, `tool:call`, `tool:result`, `llm:stream`, `engine:text`, `engine:end`, `budget:exceeded`, `engine:error`, `todo:updated`, `tool:stream-start`, `tool:stream-end`, `engine:awaiting_input`, and `engine:user_input`.

The adapter normalizes these payloads into a typed `ExecutionState`. It deduplicates event ids, probes `/api/keys-status` after repeated disconnects, streams `chunk` into the visible assistant report, and never renders private raw thinking text. `engine:end` ends running state and automatically collapses the execution block.

## Chosen architecture

Three small HTML entries (`index.html`, `login.html`, `setup.html`) load three React entry modules. Shared services, hooks, state, types, design tokens, and components live under `frontend/src`. Hash-based client navigation is used only inside the ready application (`#/`, `#/workspace`); login/setup continue to use the frozen server routes.

The state path is:

`EventSource event -> typed parser -> executionReducer -> conversation/execution UI`

HTTP calls go through one credential-aware API client. Workspace orchestration lives in a focused hook rather than page-level DOM mutation. Page components compose smaller layout, conversation, execution, and common components.

## UI design

Light mode uses paper white, warm gray, mist blue-gray, muted sage, restrained amber, and dusty clay for risk. Dark mode uses navy charcoal and warm charcoal with ivory text. Both use the same CSS-variable token names. There are no neon gradients, glass panels, terminal motifs, or dashboard-heavy result cards.

- Login: logo, product name, one password field, and submit. Password reveal temporarily darkens a light theme; a narrow amber beam originates at the right-side eye and projects left through the input.
- Home: branded top bar, single research prompt, six prompt presets, and a three-step “how it works” section.
- Workspace: resizable/collapsible history sidebar, conversation-first center, collapsible execution summary plus prose report, tasks dock and composer, and a collapsible professional right panel with Trace/Evidence/Resources tabs.
- Settings: restrained modal/page with default model and optional Planner model configuration, masked-key messaging, key validation toggle, logout, and save states.

Theme and panel preferences persist in `localStorage`. Current session persists in `sessionStorage`.

## State, errors, and privacy

Execution state explicitly represents idle, loading, running, awaiting input, completed, cancelled, and error. API errors surface near the action that caused them. EventSource disconnect is non-fatal and shown as reconnecting. A server error or cancellation unlocks the composer. Session switching closes the previous stream before loading and reconnecting.

Tool results may become evidence/resource summaries when the real payload supports that classification; no synthetic evidence, tools, skills, files, or sources are invented. Raw `agent:thinking` only changes status. No `.env`, `settings.json`, plain API key, or secret is read into or embedded in the frontend.

## Testing and acceptance

Vitest covers event reduction, report streaming, terminal auto-collapse, task updates, session time grouping, theme persistence, API redirect behavior, and masked-key payload behavior. React Testing Library covers the password reveal theme/beam behavior and main page interaction states. TypeScript strict checking and a production Vite build are required. A file-hash check confirms that all Python files are unchanged. The final static pages are inspected for inline assets and absence of secret-like values.

