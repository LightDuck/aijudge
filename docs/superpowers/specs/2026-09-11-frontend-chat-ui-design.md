# AIJudge — Frontend Chat UI Design

## Purpose

CLAUDE.md lists the frontend as one of two things still missing for a public v1.0 (alongside broader card
coverage), and the API layer spec (`docs/superpowers/specs/2026-08-27-api-layer-design.md`) explicitly deferred
it as "a separate, later spec that will consume the contract defined here." This document specs that frontend:
a single-page React chat UI that lets a user ask a Yu-Gi-Oh! rules question, answer any clarification/
disambiguation prompts, and see the final answer (or escalation/not-supported result) with citations.

Classified as **architectural** (brainstorming skill): this is a new subsystem with no existing UI flow to
modify.

## Scope

In scope: a chat-style Q&A interface that consumes exactly the two existing endpoints (`POST /questions`,
`POST /questions/answer`) as they exist today in `src/aijudge/api/app.py` and `schemas.py`. Nothing else.

Explicitly deferred (raised during brainstorming, kept in mind for later but not designed here):
- A card-browser view over the seeded card database, independent of the Q&A flow.
- An admin/debug view into call logs, confidence signals, or structured effects.

Out of scope entirely (matches the API layer's own out-of-scope list): auth, multi-tenancy, streaming/WebSocket
delivery of intermediate tool-call progress, clickable source URLs back to ygoprodeck/ygoresources.

## Stack

React + Vite + TypeScript. Chosen over plain JS or a no-build-step static page because TypeScript gives
compile-time checking against the API's typed contract — in particular the `status` discriminated union
(`"needs_clarification" | "answer" | "escalate" | "not_supported"`) and the `ClarificationItem.kind` union
(`"clarify" | "continuous_check" | "disambiguate_card"`), which is exactly the kind of thing that's easy to
mishandle with a typo if checked only at runtime. Vite over Create React App for its dev-server speed and
because the API's existing `DEFAULT_CORS_ORIGINS` (`src/aijudge/api/app.py`) already includes Vite's default
port (5173) alongside CRA's (3000).

Styling: plain CSS / CSS Modules. No Tailwind or component library — the UI is a handful of components on one
screen, and this keeps the dependency footprint minimal, matching the project's $0-cost/local-first posture.

Testing: Vitest + React Testing Library, TDD per the project's stated development process ("a failing test
precedes implementation code for every change").

## Repo layout

New top-level `frontend/` directory, sibling to `src/` and `tests/`:

```
frontend/
  package.json
  vite.config.ts
  tsconfig.json
  src/
    main.tsx
    App.tsx
    api.ts
    types.ts
    reducer.ts
    components/
      ChatHistory.tsx
      MessageBubble.tsx
      QuestionInput.tsx
      ClarificationForm.tsx
    App.css
  test/
    api.test.ts
    App.test.tsx
```

Kept independent of the Python packaging (`pyproject.toml`) entirely — a separate Node project with its own
tooling, not nested under `src/`.

## API client (`api.ts`, `types.ts`)

`types.ts` mirrors `src/aijudge/api/schemas.py` field-for-field:

```typescript
type ClarificationItemKind = "clarify" | "continuous_check" | "disambiguate_card";

interface ClarificationItem {
  kind: ClarificationItemKind;
  text: string;
}

interface Citation {
  label: string;
  text: string;
}

type ResultStatus = "answer" | "escalate" | "not_supported";

interface ResultResponse {
  status: ResultStatus;
  text: string;
  citations: Citation[] | null;
}

interface NeedsClarificationResponse {
  status: "needs_clarification";
  question: string;
  items: ClarificationItem[];
}

type QuestionResponse = ResultResponse | NeedsClarificationResponse;
```

`api.ts` exports two async functions:

- `askQuestion(question: string): Promise<QuestionResponse>` → `POST /questions`.
- `answerClarification(question: string, items: ClarificationItem[], answers: string[]): Promise<ResultResponse>`
  → `POST /questions/answer`.

Both throw a typed `ApiError` (carrying the HTTP status and, when present, the backend's generic `detail`
message) on a non-2xx response or a network failure (`fetch` rejecting) — this is the codepath backing the
error-banner behavior below. Base URL comes from `import.meta.env.VITE_AIJUDGE_API_URL`, defaulting to
`http://localhost:8000` when unset.

## State machine (`reducer.ts`, owned by `App.tsx`)

Plain `useReducer`, no Context — the component tree is shallow (`App` → `ChatHistory`/`QuestionInput`/
`ClarificationForm`, one level of `MessageBubble` under `ChatHistory`), so Context's prop-drilling fix doesn't
buy anything today. If the deferred card-browser/admin views later need to share this state, the reducer itself
is easy to lift into a Context at that point without restructuring it.

State shape:

```typescript
interface Turn {
  question: string;
  clarification?: { items: ClarificationItem[]; answers: string[] };
  result?: ResultResponse; // present once the turn is done
}

interface ChatState {
  history: Turn[];          // completed turns, oldest first
  current: Turn | null;     // the in-progress turn, or null when idle
  phase: "idle" | "submitting" | "needs_clarification" | "submitting_answer";
  error: string | null;     // set on ApiError, cleared on next submit
}
```

Actions: `ASK_SUBMITTED`, `NEEDS_CLARIFICATION`, `CLARIFICATION_SUBMITTED`, `TURN_COMPLETED`, `REQUEST_FAILED`,
`ERROR_DISMISSED`. `TURN_COMPLETED` moves `current` onto `history` and resets `phase` to `idle`. This covers
every path: a question answered immediately with no clarification; one that needs clarification (including
`disambiguate_card`) before answering; and a request that fails outright (`REQUEST_FAILED`, independent of
`current`/`history` since it may happen with no prior successful turns).

Client-side validation mirrors the API's own checks before submitting (non-empty question; for the answer
endpoint, one answer per item) purely to fail fast in the UI — the API remains the source of truth and is not
duplicated beyond this.

## Components

- **`App.tsx`** — owns the reducer; renders the error banner (if `error` is set), `ChatHistory` (for
  `history` and, when present, `current`), and either `QuestionInput` (phase `idle`) or `ClarificationForm`
  (phase `needs_clarification`), disabled during `submitting`/`submitting_answer`.
- **`ChatHistory.tsx`** — maps `Turn[]` to one block per turn: the user's question, the clarification exchange
  if any (each item's text alongside the answer given), then the result via `MessageBubble`.
- **`MessageBubble.tsx`** — renders a `ResultResponse`. `status === "answer"` renders as a plain bubble with the
  `citations` list underneath (label + text pairs). `status === "escalate"` or `"not_supported"` renders in a
  visually distinct banner style (amber for escalate, gray for not_supported) so it reads immediately as "not a
  confident grounded ruling," never mixed with a normal answer's styling.
- **`QuestionInput.tsx`** — controlled text input + submit button, calls `askQuestion` via a prop callback,
  disabled while a request is in flight.
- **`ClarificationForm.tsx`** — renders one text input per pending `ClarificationItem` (in order, including a
  `disambiguate_card` item as just another text prompt — its text already states the candidate names), submits
  all answers together via `answerClarification`.

## Error handling

An `ApiError` (network failure, or the API's own `400`/`422`/`503`/`500`) sets `ChatState.error` and renders as
a dismissible banner at the top of the page — distinct from the escalate/not_supported `MessageBubble` styling,
since those are valid backend results and this is "the backend could not be reached or rejected the request
outright." Dismissing clears `error` without discarding `history`; the failed turn is not added to `history` (it
never completed).

## Testing

`test/api.test.ts` mocks global `fetch` and asserts, per function: the request URL/method/body shape sent, and
correct parsing of each response shape (`needs_clarification`, all three `ResultResponse.status` values, and a
non-2xx response producing a thrown `ApiError` with the right status/detail).

`test/App.test.tsx` (React Testing Library) drives the full component tree with a mocked `api.ts` module through:
1. Ask a question → immediate `"answer"` result with citations rendered.
2. Ask a question → `needs_clarification` (plain `clarify`/`continuous_check` items) → submit answers →
   `"answer"` result; both turns visible in history.
3. Ask a question → `needs_clarification` with a `disambiguate_card` item → submit → `"answer"` result.
4. Ask a question → `"not_supported"` result rendered in its distinct banner style.
5. Ask a question → simulated network failure → error banner shown, no turn added to history, input re-enabled.

No real backend in any test — matches how `tests/api` (Python) mocks the LLM/embedding clients rather than
hitting Ollama/Postgres.

## Dev workflow

`npm install && npm run dev` inside `frontend/` (Vite dev server, default port 5173) alongside
`python -m aijudge.api` for the backend (default port 8000, matching `DEFAULT_PORT` in
`src/aijudge/api/__main__.py`). `VITE_AIJUDGE_API_URL` overrides the API base URL when the backend isn't on the
default host/port. `README.md` gets a short "Running the frontend" section covering both commands and the env
var.

## Out of scope

- The card-browser and admin/debug views raised during brainstorming — separate future specs if pursued.
- Any change to the existing API contract (`src/aijudge/api/`) — this frontend consumes it as-is.
- Production build/deployment (a static `npm run build` output and how/where it's served) — this spec covers
  the dev-time UI only, consistent with the project's current local-single-user scope.
