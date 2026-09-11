# AIJudge Frontend Chat UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-page React chat UI that lets a user ask a Yu-Gi-Oh! rules question, answer any
clarification/disambiguation prompts, and see the final answer (or escalation/not-supported result) with
citations, consuming the existing `POST /questions` / `POST /questions/answer` API exactly as it exists today.

**Architecture:** A new top-level `frontend/` Vite + React + TypeScript project. A typed `api.ts` client wraps
the two endpoints; a single `useReducer`-driven state machine in `App.tsx` drives the ask → (optional
clarification round-trip) → result flow, rendering a scrolling `ChatHistory` of completed turns plus the active
input form.

**Tech Stack:** React 18, Vite, TypeScript (strict), plain CSS (no Tailwind/component library, no Context/Redux),
Vitest + React Testing Library for TDD.

**Spec:** `docs/superpowers/specs/2026-09-11-frontend-chat-ui-design.md`

## Global Constraints

- Repo location: new top-level `frontend/` directory, independent of the Python packaging (`pyproject.toml`) —
  its own `package.json`/`vite.config.ts`/`tsconfig.json`.
- Stack: React 18 + Vite + TypeScript in strict mode. Plain CSS only — no Tailwind, no component library.
- State management: a single `useReducer` owned by `App.tsx`. No React Context, no Redux/Zustand/other store.
- Do not modify the Python API (`src/aijudge/api/`) — this frontend consumes it exactly as implemented today.
- Endpoints consumed: `POST /questions` and `POST /questions/answer` only.
- Type contract mirrors `src/aijudge/api/schemas.py` field-for-field: `ClarificationItem.kind` is one of
  `"clarify" | "continuous_check" | "disambiguate_card"`; `ResultResponse.status` is one of
  `"answer" | "escalate" | "not_supported"`; `NeedsClarificationResponse.status` is exactly
  `"needs_clarification"`; `Citation` is `{label: string, text: string}`.
- API base URL comes from `import.meta.env.VITE_AIJUDGE_API_URL`, defaulting to `http://localhost:8000` when
  unset.
- Testing: Vitest + React Testing Library. TDD — a failing test precedes implementation code for every task, per
  this project's development process. No real network/backend calls in any test.
- Vite dev server runs on its default port, 5173 — already present in the API's `DEFAULT_CORS_ORIGINS`
  (`src/aijudge/api/app.py`).

---

## Task 1: Project scaffold (Vite + React + TypeScript + Vitest)

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/.gitignore`
- Create: `frontend/test/setup.ts`
- Create: `frontend/src/vite-env.d.ts`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/App.css`
- Test: `frontend/test/App.test.tsx`

**Interfaces:**
- Produces: a working `npm run dev` / `npm test` toolchain in `frontend/`; a default-exported `App` component
  from `frontend/src/App.tsx` that later tasks will extend (not replace) in Task 8.

- [ ] **Step 1: Create the scaffold/config files**

`frontend/package.json`:
```json
{
  "name": "aijudge-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.4.8",
    "@testing-library/react": "^14.3.1",
    "@testing-library/user-event": "^14.5.2",
    "@types/react": "^18.3.5",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "jsdom": "^24.1.1",
    "typescript": "^5.5.4",
    "vite": "^5.4.2",
    "vitest": "^2.0.5"
  }
}
```

`frontend/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src", "test"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

`frontend/tsconfig.node.json`:
```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true
  },
  "include": ["vite.config.ts"]
}
```

`frontend/vite.config.ts`:
```typescript
/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./test/setup.ts",
  },
});
```

`frontend/index.html`:
```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>AIJudge</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`frontend/.gitignore`:
```
node_modules
dist
.env
.env.local
```

`frontend/test/setup.ts`:
```typescript
import "@testing-library/jest-dom/vitest";
```

`frontend/src/vite-env.d.ts`:
```typescript
/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_AIJUDGE_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
```

- [ ] **Step 2: Install dependencies**

Run: `cd frontend && npm install`
Expected: installs without errors, creates `frontend/node_modules` and `frontend/package-lock.json`.

- [ ] **Step 3: Write the failing smoke test**

`frontend/test/App.test.tsx`:
```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import App from "../src/App";

describe("App", () => {
  it("renders the app title", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "AIJudge" })).toBeInTheDocument();
  });
});
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `npm test` (from `frontend/`)
Expected: FAIL — `frontend/src/App.tsx` does not exist yet (module not found).

- [ ] **Step 5: Write the minimal App shell**

`frontend/src/App.tsx`:
```tsx
export default function App() {
  return (
    <div className="app">
      <h1>AIJudge</h1>
    </div>
  );
}
```

`frontend/src/App.css`:
```css
.app {
  max-width: 720px;
  margin: 0 auto;
  padding: 1.5rem;
  font-family: system-ui, sans-serif;
}
```

`frontend/src/main.tsx`:
```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./App.css";

const container = document.getElementById("root");
if (!container) {
  throw new Error("Root element not found");
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `npm test` (from `frontend/`)
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/package.json frontend/tsconfig.json frontend/tsconfig.node.json frontend/vite.config.ts \
  frontend/index.html frontend/.gitignore frontend/test/setup.ts frontend/src/vite-env.d.ts \
  frontend/src/main.tsx frontend/src/App.tsx frontend/src/App.css frontend/test/App.test.tsx \
  frontend/package-lock.json
git commit -m "feat(frontend): scaffold Vite + React + TypeScript + Vitest project"
```

---

## Task 2: API client (`types.ts`, `api.ts`)

**Files:**
- Create: `frontend/src/types.ts`
- Create: `frontend/src/api.ts`
- Test: `frontend/test/api.test.ts`

**Interfaces:**
- Produces:
  - Types: `ClarificationItemKind`, `ClarificationItem`, `Citation`, `ResultStatus`, `ResultResponse`,
    `NeedsClarificationResponse`, `QuestionResponse` (all from `types.ts`).
  - `class ApiError extends Error { status: number; detail: string | null }` (from `api.ts`).
  - `askQuestion(question: string): Promise<QuestionResponse>` (from `api.ts`).
  - `answerClarification(question: string, items: ClarificationItem[], answers: string[]): Promise<ResultResponse>`
    (from `api.ts`).

- [ ] **Step 1: Write the failing tests**

`frontend/test/api.test.ts`:
```typescript
import { describe, it, expect, beforeEach, vi } from "vitest";
import { askQuestion, answerClarification, ApiError } from "../src/api";

function mockFetchOnce(status: number, body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    }),
  );
}

describe("askQuestion", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends a POST to /questions with the question and returns an answer result", async () => {
    mockFetchOnce(200, {
      status: "answer",
      text: "Yes.",
      citations: [{ label: "Card", text: "..." }],
    });

    const result = await askQuestion("Does X negate Y?");

    expect(result).toEqual({ status: "answer", text: "Yes.", citations: [{ label: "Card", text: "..." }] });
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/questions",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ question: "Does X negate Y?" }),
      }),
    );
  });

  it("returns a needs_clarification result", async () => {
    mockFetchOnce(200, {
      status: "needs_clarification",
      question: "Does X negate Y?",
      items: [{ kind: "clarify", text: "Which turn?" }],
    });

    const result = await askQuestion("Does X negate Y?");

    expect(result).toEqual({
      status: "needs_clarification",
      question: "Does X negate Y?",
      items: [{ kind: "clarify", text: "Which turn?" }],
    });
  });

  it("returns an escalate result", async () => {
    mockFetchOnce(200, { status: "escalate", text: "Ask a judge.", citations: null });

    const result = await askQuestion("Some edge case?");

    expect(result).toEqual({ status: "escalate", text: "Ask a judge.", citations: null });
  });

  it("returns a not_supported result", async () => {
    mockFetchOnce(200, { status: "not_supported", text: "Not supported yet.", citations: null });

    const result = await askQuestion("Some unsupported scenario?");

    expect(result).toEqual({ status: "not_supported", text: "Not supported yet.", citations: null });
  });

  it("throws an ApiError with the backend detail on a non-2xx response", async () => {
    mockFetchOnce(400, { detail: "question must not be empty" });

    await expect(askQuestion("")).rejects.toMatchObject({
      name: "ApiError",
      status: 400,
      detail: "question must not be empty",
    });
  });

  it("throws an ApiError on a network failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));

    await expect(askQuestion("Does X negate Y?")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("answerClarification", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends a POST to /questions/answer with items and answers and returns a result", async () => {
    mockFetchOnce(200, { status: "answer", text: "Yes.", citations: [] });

    const items = [{ kind: "clarify" as const, text: "Which turn?" }];
    const result = await answerClarification("Does X negate Y?", items, ["My turn"]);

    expect(result).toEqual({ status: "answer", text: "Yes.", citations: [] });
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/questions/answer",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ question: "Does X negate Y?", items, answers: ["My turn"] }),
      }),
    );
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test` (from `frontend/`)
Expected: FAIL — `frontend/src/api.ts` does not exist yet.

- [ ] **Step 3: Write `types.ts` and `api.ts`**

`frontend/src/types.ts`:
```typescript
export type ClarificationItemKind = "clarify" | "continuous_check" | "disambiguate_card";

export interface ClarificationItem {
  kind: ClarificationItemKind;
  text: string;
}

export interface Citation {
  label: string;
  text: string;
}

export type ResultStatus = "answer" | "escalate" | "not_supported";

export interface ResultResponse {
  status: ResultStatus;
  text: string;
  citations: Citation[] | null;
}

export interface NeedsClarificationResponse {
  status: "needs_clarification";
  question: string;
  items: ClarificationItem[];
}

export type QuestionResponse = ResultResponse | NeedsClarificationResponse;
```

`frontend/src/api.ts`:
```typescript
import type { ClarificationItem, QuestionResponse, ResultResponse } from "./types";

const BASE_URL = import.meta.env.VITE_AIJUDGE_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string | null;

  constructor(status: number, detail: string | null) {
    super(detail ? `API error ${status}: ${detail}` : `API error ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "network error: could not reach the backend");
  }

  if (!response.ok) {
    let detail: string | null = null;
    try {
      const errorBody = (await response.json()) as { detail?: string };
      detail = errorBody.detail ?? null;
    } catch {
      detail = null;
    }
    throw new ApiError(response.status, detail);
  }

  return (await response.json()) as T;
}

export function askQuestion(question: string): Promise<QuestionResponse> {
  return postJson<QuestionResponse>("/questions", { question });
}

export function answerClarification(
  question: string,
  items: ClarificationItem[],
  answers: string[],
): Promise<ResultResponse> {
  return postJson<ResultResponse>("/questions/answer", { question, items, answers });
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test` (from `frontend/`)
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types.ts frontend/src/api.ts frontend/test/api.test.ts
git commit -m "feat(frontend): add typed API client for /questions and /questions/answer"
```

---

## Task 3: Chat state machine (`reducer.ts`)

**Files:**
- Create: `frontend/src/reducer.ts`
- Test: `frontend/test/reducer.test.ts`

**Interfaces:**
- Consumes: `ClarificationItem`, `ResultResponse` (from `frontend/src/types.ts`, Task 2).
- Produces: `Turn`, `ChatPhase`, `ChatState`, `ChatAction`, `initialChatState: ChatState`,
  `chatReducer(state: ChatState, action: ChatAction): ChatState`.

- [ ] **Step 1: Write the failing tests**

`frontend/test/reducer.test.ts`:
```typescript
import { describe, it, expect } from "vitest";
import { chatReducer, initialChatState } from "../src/reducer";
import type { ChatState } from "../src/reducer";

describe("chatReducer", () => {
  it("starts a new turn on ASK_SUBMITTED and clears any prior error", () => {
    const withError: ChatState = { ...initialChatState, error: "previous failure" };

    const next = chatReducer(withError, { type: "ASK_SUBMITTED", question: "Does X negate Y?" });

    expect(next).toEqual({
      history: [],
      current: { question: "Does X negate Y?" },
      phase: "submitting",
      error: null,
    });
  });

  it("attaches clarification items on NEEDS_CLARIFICATION", () => {
    const submitting: ChatState = {
      ...initialChatState,
      current: { question: "Does X negate Y?" },
      phase: "submitting",
    };
    const items = [{ kind: "clarify" as const, text: "Whose turn?" }];

    const next = chatReducer(submitting, { type: "NEEDS_CLARIFICATION", items });

    expect(next.phase).toBe("needs_clarification");
    expect(next.current).toEqual({ question: "Does X negate Y?", clarification: { items, answers: [] } });
  });

  it("does nothing on NEEDS_CLARIFICATION when there is no current turn", () => {
    const next = chatReducer(initialChatState, {
      type: "NEEDS_CLARIFICATION",
      items: [{ kind: "clarify", text: "Whose turn?" }],
    });

    expect(next).toEqual(initialChatState);
  });

  it("records answers and moves to submitting_answer on CLARIFICATION_SUBMITTED", () => {
    const items = [{ kind: "clarify" as const, text: "Whose turn?" }];
    const needsClarification: ChatState = {
      ...initialChatState,
      current: { question: "Does X negate Y?", clarification: { items, answers: [] } },
      phase: "needs_clarification",
    };

    const next = chatReducer(needsClarification, { type: "CLARIFICATION_SUBMITTED", answers: ["My turn"] });

    expect(next.phase).toBe("submitting_answer");
    expect(next.current).toEqual({
      question: "Does X negate Y?",
      clarification: { items, answers: ["My turn"] },
    });
  });

  it("moves the current turn into history and resets to idle on TURN_COMPLETED", () => {
    const submitting: ChatState = {
      ...initialChatState,
      current: { question: "Does X negate Y?" },
      phase: "submitting",
    };
    const result = { status: "answer" as const, text: "Yes.", citations: [] };

    const next = chatReducer(submitting, { type: "TURN_COMPLETED", result });

    expect(next).toEqual({
      history: [{ question: "Does X negate Y?", result }],
      current: null,
      phase: "idle",
      error: null,
    });
  });

  it("does nothing on TURN_COMPLETED when there is no current turn", () => {
    const result = { status: "answer" as const, text: "Yes.", citations: [] };

    const next = chatReducer(initialChatState, { type: "TURN_COMPLETED", result });

    expect(next).toEqual(initialChatState);
  });

  it("clears the current turn and sets an error message on REQUEST_FAILED", () => {
    const submitting: ChatState = {
      ...initialChatState,
      current: { question: "Does X negate Y?" },
      phase: "submitting",
    };

    const next = chatReducer(submitting, { type: "REQUEST_FAILED", message: "backend unavailable" });

    expect(next).toEqual({
      history: [],
      current: null,
      phase: "idle",
      error: "backend unavailable",
    });
  });

  it("clears the error on ERROR_DISMISSED without touching history", () => {
    const withError: ChatState = {
      ...initialChatState,
      history: [{ question: "Q", result: { status: "answer", text: "A", citations: [] } }],
      error: "backend unavailable",
    };

    const next = chatReducer(withError, { type: "ERROR_DISMISSED" });

    expect(next.error).toBeNull();
    expect(next.history).toEqual(withError.history);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test` (from `frontend/`)
Expected: FAIL — `frontend/src/reducer.ts` does not exist yet.

- [ ] **Step 3: Write `reducer.ts`**

`frontend/src/reducer.ts`:
```typescript
import type { ClarificationItem, ResultResponse } from "./types";

export interface Turn {
  question: string;
  clarification?: { items: ClarificationItem[]; answers: string[] };
  result?: ResultResponse;
}

export type ChatPhase = "idle" | "submitting" | "needs_clarification" | "submitting_answer";

export interface ChatState {
  history: Turn[];
  current: Turn | null;
  phase: ChatPhase;
  error: string | null;
}

export type ChatAction =
  | { type: "ASK_SUBMITTED"; question: string }
  | { type: "NEEDS_CLARIFICATION"; items: ClarificationItem[] }
  | { type: "CLARIFICATION_SUBMITTED"; answers: string[] }
  | { type: "TURN_COMPLETED"; result: ResultResponse }
  | { type: "REQUEST_FAILED"; message: string }
  | { type: "ERROR_DISMISSED" };

export const initialChatState: ChatState = {
  history: [],
  current: null,
  phase: "idle",
  error: null,
};

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "ASK_SUBMITTED":
      return {
        ...state,
        current: { question: action.question },
        phase: "submitting",
        error: null,
      };
    case "NEEDS_CLARIFICATION": {
      if (!state.current) {
        return state;
      }
      return {
        ...state,
        current: { ...state.current, clarification: { items: action.items, answers: [] } },
        phase: "needs_clarification",
      };
    }
    case "CLARIFICATION_SUBMITTED": {
      if (!state.current || !state.current.clarification) {
        return state;
      }
      return {
        ...state,
        current: {
          ...state.current,
          clarification: { ...state.current.clarification, answers: action.answers },
        },
        phase: "submitting_answer",
      };
    }
    case "TURN_COMPLETED": {
      if (!state.current) {
        return state;
      }
      const completedTurn: Turn = { ...state.current, result: action.result };
      return {
        ...state,
        history: [...state.history, completedTurn],
        current: null,
        phase: "idle",
      };
    }
    case "REQUEST_FAILED":
      return {
        ...state,
        current: null,
        phase: "idle",
        error: action.message,
      };
    case "ERROR_DISMISSED":
      return {
        ...state,
        error: null,
      };
    default:
      return state;
  }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test` (from `frontend/`)
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/reducer.ts frontend/test/reducer.test.ts
git commit -m "feat(frontend): add chat state machine reducer"
```

---

## Task 4: `MessageBubble` component

**Files:**
- Create: `frontend/src/components/MessageBubble.tsx`
- Modify: `frontend/src/App.css`
- Test: `frontend/test/components/MessageBubble.test.tsx`

**Interfaces:**
- Consumes: `ResultResponse` (from `frontend/src/types.ts`, Task 2).
- Produces: default export `MessageBubble({ result: ResultResponse })`. CSS classes:
  `message-bubble`, `message-bubble--answer`, `message-bubble--escalate`, `message-bubble--not-supported`,
  `message-bubble__citations`.

- [ ] **Step 1: Write the failing tests**

`frontend/test/components/MessageBubble.test.tsx`:
```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import MessageBubble from "../../src/components/MessageBubble";

describe("MessageBubble", () => {
  it("renders an answer with its citations", () => {
    render(
      <MessageBubble
        result={{
          status: "answer",
          text: "Yes, it negates the activation.",
          citations: [{ label: "Effect Veiler", text: "Negates the activation of a Monster Effect." }],
        }}
      />,
    );

    expect(screen.getByText("Yes, it negates the activation.")).toBeInTheDocument();
    expect(screen.getByText(/Effect Veiler:/)).toBeInTheDocument();
  });

  it("renders an answer with no citations without a citation list", () => {
    render(<MessageBubble result={{ status: "answer", text: "Yes.", citations: [] }} />);

    expect(screen.getByText("Yes.")).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("renders an escalate result in its distinct banner style", () => {
    render(<MessageBubble result={{ status: "escalate", text: "Ask a judge.", citations: null }} />);

    const banner = screen.getByRole("status");
    expect(banner).toHaveClass("message-bubble--escalate");
    expect(banner).toHaveTextContent("Ask a judge.");
  });

  it("renders a not_supported result in its distinct banner style", () => {
    render(<MessageBubble result={{ status: "not_supported", text: "Not supported yet.", citations: null }} />);

    const banner = screen.getByRole("status");
    expect(banner).toHaveClass("message-bubble--not-supported");
    expect(banner).toHaveTextContent("Not supported yet.");
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test` (from `frontend/`)
Expected: FAIL — `frontend/src/components/MessageBubble.tsx` does not exist yet.

- [ ] **Step 3: Write `MessageBubble.tsx` and its styles**

`frontend/src/components/MessageBubble.tsx`:
```tsx
import type { ResultResponse } from "../types";

interface MessageBubbleProps {
  result: ResultResponse;
}

export default function MessageBubble({ result }: MessageBubbleProps) {
  if (result.status === "answer") {
    return (
      <div className="message-bubble message-bubble--answer">
        <p>{result.text}</p>
        {result.citations && result.citations.length > 0 && (
          <ul className="message-bubble__citations">
            {result.citations.map((citation, index) => (
              <li key={index}>
                <strong>{citation.label}:</strong> {citation.text}
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  const bannerClass =
    result.status === "escalate"
      ? "message-bubble message-bubble--escalate"
      : "message-bubble message-bubble--not-supported";

  return (
    <div className={bannerClass} role="status">
      <p>{result.text}</p>
    </div>
  );
}
```

Append to `frontend/src/App.css`:
```css
.message-bubble {
  border-radius: 0.5rem;
  padding: 0.75rem 1rem;
  margin: 0.5rem 0;
}

.message-bubble--answer {
  background: #eef3ff;
}

.message-bubble--escalate {
  background: #fff3cd;
  border: 1px solid #d8a900;
}

.message-bubble--not-supported {
  background: #eceff1;
  border: 1px solid #90a4ae;
}

.message-bubble__citations {
  margin-top: 0.5rem;
  padding-left: 1.25rem;
  font-size: 0.9rem;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test` (from `frontend/`)
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/MessageBubble.tsx frontend/src/App.css \
  frontend/test/components/MessageBubble.test.tsx
git commit -m "feat(frontend): add MessageBubble component"
```

---

## Task 5: `QuestionInput` component

**Files:**
- Create: `frontend/src/components/QuestionInput.tsx`
- Modify: `frontend/src/App.css`
- Test: `frontend/test/components/QuestionInput.test.tsx`

**Interfaces:**
- Produces: default export `QuestionInput({ onSubmit: (question: string) => void, disabled: boolean })`.
  CSS class: `question-input`.

- [ ] **Step 1: Write the failing tests**

`frontend/test/components/QuestionInput.test.tsx`:
```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import QuestionInput from "../../src/components/QuestionInput";

describe("QuestionInput", () => {
  it("submits the trimmed question and clears the input", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<QuestionInput onSubmit={onSubmit} disabled={false} />);

    await user.type(screen.getByLabelText("Question"), "  Does X negate Y?  ");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    expect(onSubmit).toHaveBeenCalledWith("Does X negate Y?");
    expect(screen.getByLabelText("Question")).toHaveValue("");
  });

  it("does not submit a blank question", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<QuestionInput onSubmit={onSubmit} disabled={false} />);

    await user.type(screen.getByLabelText("Question"), "   ");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("disables the input and button when disabled is true", () => {
    render(<QuestionInput onSubmit={vi.fn()} disabled={true} />);

    expect(screen.getByLabelText("Question")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test` (from `frontend/`)
Expected: FAIL — `frontend/src/components/QuestionInput.tsx` does not exist yet.

- [ ] **Step 3: Write `QuestionInput.tsx` and its styles**

`frontend/src/components/QuestionInput.tsx`:
```tsx
import { useState } from "react";
import type { FormEvent } from "react";

interface QuestionInputProps {
  onSubmit: (question: string) => void;
  disabled: boolean;
}

export default function QuestionInput({ onSubmit, disabled }: QuestionInputProps) {
  const [value, setValue] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = value.trim();
    if (!trimmed) {
      return;
    }
    onSubmit(trimmed);
    setValue("");
  }

  return (
    <form onSubmit={handleSubmit} className="question-input">
      <input
        type="text"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder="Ask a Yu-Gi-Oh! rules question..."
        disabled={disabled}
        aria-label="Question"
      />
      <button type="submit" disabled={disabled}>
        Ask
      </button>
    </form>
  );
}
```

Append to `frontend/src/App.css`:
```css
.question-input {
  display: flex;
  gap: 0.5rem;
  margin-top: 1rem;
}

.question-input input {
  flex: 1;
  padding: 0.5rem;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test` (from `frontend/`)
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/QuestionInput.tsx frontend/src/App.css \
  frontend/test/components/QuestionInput.test.tsx
git commit -m "feat(frontend): add QuestionInput component"
```

---

## Task 6: `ClarificationForm` component

**Files:**
- Create: `frontend/src/components/ClarificationForm.tsx`
- Modify: `frontend/src/App.css`
- Test: `frontend/test/components/ClarificationForm.test.tsx`

**Interfaces:**
- Consumes: `ClarificationItem` (from `frontend/src/types.ts`, Task 2).
- Produces: default export
  `ClarificationForm({ items: ClarificationItem[], onSubmit: (answers: string[]) => void, disabled: boolean })`.
  CSS classes: `clarification-form`, `clarification-form__item`.

- [ ] **Step 1: Write the failing tests**

`frontend/test/components/ClarificationForm.test.tsx`:
```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ClarificationForm from "../../src/components/ClarificationForm";

describe("ClarificationForm", () => {
  it("renders one input per item and submits answers in order", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    const items = [
      { kind: "clarify" as const, text: "Whose turn is it?" },
      { kind: "continuous_check" as const, text: "Is the continuous effect currently active?" },
    ];
    render(<ClarificationForm items={items} onSubmit={onSubmit} disabled={false} />);

    await user.type(screen.getByLabelText("Whose turn is it?"), "My turn");
    await user.type(screen.getByLabelText("Is the continuous effect currently active?"), "Yes");
    await user.click(screen.getByRole("button", { name: "Submit" }));

    expect(onSubmit).toHaveBeenCalledWith(["My turn", "Yes"]);
  });

  it("disables all inputs and the submit button when disabled is true", () => {
    const items = [{ kind: "clarify" as const, text: "Whose turn is it?" }];
    render(<ClarificationForm items={items} onSubmit={vi.fn()} disabled={true} />);

    expect(screen.getByLabelText("Whose turn is it?")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test` (from `frontend/`)
Expected: FAIL — `frontend/src/components/ClarificationForm.tsx` does not exist yet.

- [ ] **Step 3: Write `ClarificationForm.tsx` and its styles**

`frontend/src/components/ClarificationForm.tsx`:
```tsx
import { useState } from "react";
import type { FormEvent } from "react";
import type { ClarificationItem } from "../types";

interface ClarificationFormProps {
  items: ClarificationItem[];
  onSubmit: (answers: string[]) => void;
  disabled: boolean;
}

export default function ClarificationForm({ items, onSubmit, disabled }: ClarificationFormProps) {
  const [answers, setAnswers] = useState<string[]>(() => items.map(() => ""));

  function handleChange(index: number, value: string) {
    setAnswers((prev) => prev.map((answer, i) => (i === index ? value : answer)));
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit(answers);
  }

  return (
    <form onSubmit={handleSubmit} className="clarification-form">
      {items.map((item, index) => (
        <label key={index} className="clarification-form__item">
          <span>{item.text}</span>
          <input
            type="text"
            value={answers[index]}
            onChange={(event) => handleChange(index, event.target.value)}
            disabled={disabled}
            aria-label={item.text}
          />
        </label>
      ))}
      <button type="submit" disabled={disabled}>
        Submit
      </button>
    </form>
  );
}
```

Append to `frontend/src/App.css`:
```css
.clarification-form {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  margin-top: 1rem;
}

.clarification-form__item {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.clarification-form__item input {
  padding: 0.5rem;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test` (from `frontend/`)
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ClarificationForm.tsx frontend/src/App.css \
  frontend/test/components/ClarificationForm.test.tsx
git commit -m "feat(frontend): add ClarificationForm component"
```

---

## Task 7: `ChatHistory` component

**Files:**
- Create: `frontend/src/components/ChatHistory.tsx`
- Modify: `frontend/src/App.css`
- Test: `frontend/test/components/ChatHistory.test.tsx`

**Interfaces:**
- Consumes: `Turn` (from `frontend/src/reducer.ts`, Task 3), `MessageBubble` (from
  `frontend/src/components/MessageBubble.tsx`, Task 4).
- Produces: default export `ChatHistory({ turns: Turn[] })`. CSS classes: `chat-history`,
  `chat-history__turn`, `chat-history__question`, `chat-history__clarification`,
  `chat-history__clarification-item`.

- [ ] **Step 1: Write the failing tests**

`frontend/test/components/ChatHistory.test.tsx`:
```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import ChatHistory from "../../src/components/ChatHistory";
import type { Turn } from "../../src/reducer";

describe("ChatHistory", () => {
  it("renders nothing for an empty history", () => {
    const { container } = render(<ChatHistory turns={[]} />);
    expect(container.querySelector(".chat-history")?.children.length).toBe(0);
  });

  it("renders a turn's question and its answer", () => {
    const turns: Turn[] = [
      { question: "Does X negate Y?", result: { status: "answer", text: "Yes.", citations: [] } },
    ];

    render(<ChatHistory turns={turns} />);

    expect(screen.getByText("Does X negate Y?")).toBeInTheDocument();
    expect(screen.getByText("Yes.")).toBeInTheDocument();
  });

  it("renders the clarification question and the answer given, alongside the final result", () => {
    const turns: Turn[] = [
      {
        question: "Does X work during my turn?",
        clarification: { items: [{ kind: "clarify", text: "Whose turn is it?" }], answers: ["My turn"] },
        result: { status: "answer", text: "Yes, on your turn it works.", citations: [] },
      },
    ];

    render(<ChatHistory turns={turns} />);

    expect(screen.getByText("Whose turn is it?", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("My turn", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("Yes, on your turn it works.")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test` (from `frontend/`)
Expected: FAIL — `frontend/src/components/ChatHistory.tsx` does not exist yet.

- [ ] **Step 3: Write `ChatHistory.tsx` and its styles**

`frontend/src/components/ChatHistory.tsx`:
```tsx
import type { Turn } from "../reducer";
import MessageBubble from "./MessageBubble";

interface ChatHistoryProps {
  turns: Turn[];
}

export default function ChatHistory({ turns }: ChatHistoryProps) {
  return (
    <div className="chat-history">
      {turns.map((turn, index) => (
        <div key={index} className="chat-history__turn">
          <p className="chat-history__question">{turn.question}</p>
          {turn.clarification && (
            <div className="chat-history__clarification">
              {turn.clarification.items.map((item, itemIndex) => (
                <p key={itemIndex} className="chat-history__clarification-item">
                  <em>{item.text}</em> — {turn.clarification!.answers[itemIndex]}
                </p>
              ))}
            </div>
          )}
          {turn.result && <MessageBubble result={turn.result} />}
        </div>
      ))}
    </div>
  );
}
```

Append to `frontend/src/App.css`:
```css
.chat-history__turn {
  border-bottom: 1px solid #e0e0e0;
  padding-bottom: 0.75rem;
  margin-bottom: 0.75rem;
}

.chat-history__question {
  font-weight: 600;
}

.chat-history__clarification-item {
  font-size: 0.9rem;
  color: #555;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test` (from `frontend/`)
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ChatHistory.tsx frontend/src/App.css \
  frontend/test/components/ChatHistory.test.tsx
git commit -m "feat(frontend): add ChatHistory component"
```

---

## Task 8: Wire `App.tsx` end-to-end

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.css`
- Modify: `frontend/test/App.test.tsx`

**Interfaces:**
- Consumes: `askQuestion`, `answerClarification`, `ApiError` (`frontend/src/api.ts`, Task 2); `chatReducer`,
  `initialChatState` (`frontend/src/reducer.ts`, Task 3); `ChatHistory` (Task 7); `QuestionInput` (Task 5);
  `ClarificationForm` (Task 6).
- Produces: the finished default export `App` (root component).

- [ ] **Step 1: Write the failing integration tests**

Replace the contents of `frontend/test/App.test.tsx` with:
```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../src/App";
import { ApiError } from "../src/api";

vi.mock("../src/api", async () => {
  const actual = await vi.importActual<typeof import("../src/api")>("../src/api");
  return {
    ...actual,
    askQuestion: vi.fn(),
    answerClarification: vi.fn(),
  };
});

import { askQuestion, answerClarification } from "../src/api";

describe("App", () => {
  beforeEach(() => {
    vi.mocked(askQuestion).mockReset();
    vi.mocked(answerClarification).mockReset();
  });

  it("renders the app title", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "AIJudge" })).toBeInTheDocument();
  });

  it("asks a question and shows an immediate answer with citations", async () => {
    vi.mocked(askQuestion).mockResolvedValue({
      status: "answer",
      text: "Yes, it negates the activation.",
      citations: [{ label: "Effect Veiler", text: "..." }],
    });
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByLabelText("Question"), "Does Effect Veiler negate X?");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText("Yes, it negates the activation.")).toBeInTheDocument();
    expect(screen.getByText(/Effect Veiler:/)).toBeInTheDocument();
  });

  it("asks a question, resolves a clarification round-trip, and shows the answer with both turns in history", async () => {
    vi.mocked(askQuestion).mockResolvedValue({
      status: "needs_clarification",
      question: "Does X work during my turn?",
      items: [{ kind: "clarify", text: "Whose turn is it?" }],
    });
    vi.mocked(answerClarification).mockResolvedValue({
      status: "answer",
      text: "Yes, on your turn it works.",
      citations: [],
    });
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByLabelText("Question"), "Does X work during my turn?");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByLabelText("Whose turn is it?")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Whose turn is it?"), "My turn");
    await user.click(screen.getByRole("button", { name: "Submit" }));

    expect(await screen.findByText("Yes, on your turn it works.")).toBeInTheDocument();
    expect(answerClarification).toHaveBeenCalledWith(
      "Does X work during my turn?",
      [{ kind: "clarify", text: "Whose turn is it?" }],
      ["My turn"],
    );
    expect(screen.getByText("Does X work during my turn?")).toBeInTheDocument();
  });

  it("resolves a disambiguate_card clarification item like any other item", async () => {
    vi.mocked(askQuestion).mockResolvedValue({
      status: "needs_clarification",
      question: "What does it do?",
      items: [
        {
          kind: "disambiguate_card",
          text: "Multiple cards match: Effect Veiler, Effect Voiler. Which one do you mean?",
        },
      ],
    });
    vi.mocked(answerClarification).mockResolvedValue({
      status: "answer",
      text: "Effect Veiler negates the activation of a monster effect.",
      citations: [],
    });
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByLabelText("Question"), "What does it do?");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    const prompt = "Multiple cards match: Effect Veiler, Effect Voiler. Which one do you mean?";
    await user.type(screen.getByLabelText(prompt), "Effect Veiler");
    await user.click(screen.getByRole("button", { name: "Submit" }));

    expect(
      await screen.findByText("Effect Veiler negates the activation of a monster effect."),
    ).toBeInTheDocument();
  });

  it("shows a not_supported result in its distinct banner", async () => {
    vi.mocked(askQuestion).mockResolvedValue({
      status: "not_supported",
      text: "This scenario isn't supported yet.",
      citations: null,
    });
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByLabelText("Question"), "Some unsupported scenario?");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    const banner = await screen.findByRole("status");
    expect(banner).toHaveClass("message-bubble--not-supported");
    expect(banner).toHaveTextContent("This scenario isn't supported yet.");
  });

  it("shows a dismissible error banner on a network failure and re-enables the input without adding a turn", async () => {
    vi.mocked(askQuestion).mockRejectedValue(new ApiError(0, "network error: could not reach the backend"));
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByLabelText("Question"), "Does X negate Y?");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("network error: could not reach the backend");
    expect(screen.getByLabelText("Question")).not.toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npm test` (from `frontend/`)
Expected: FAIL — the current `App.tsx` has no input, no clarification handling, no error banner.

- [ ] **Step 3: Wire up `App.tsx` and its styles**

Replace the contents of `frontend/src/App.tsx` with:
```tsx
import { useReducer } from "react";
import { answerClarification, askQuestion, ApiError } from "./api";
import { chatReducer, initialChatState } from "./reducer";
import ChatHistory from "./components/ChatHistory";
import ClarificationForm from "./components/ClarificationForm";
import QuestionInput from "./components/QuestionInput";

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    return error.detail ?? `Request failed (status ${error.status}).`;
  }
  return "Something went wrong. Please try again.";
}

export default function App() {
  const [state, dispatch] = useReducer(chatReducer, initialChatState);

  async function handleAsk(question: string) {
    dispatch({ type: "ASK_SUBMITTED", question });
    try {
      const response = await askQuestion(question);
      if (response.status === "needs_clarification") {
        dispatch({ type: "NEEDS_CLARIFICATION", items: response.items });
      } else {
        dispatch({ type: "TURN_COMPLETED", result: response });
      }
    } catch (error) {
      dispatch({ type: "REQUEST_FAILED", message: describeError(error) });
    }
  }

  async function handleClarificationSubmit(answers: string[]) {
    if (!state.current || !state.current.clarification) {
      return;
    }
    dispatch({ type: "CLARIFICATION_SUBMITTED", answers });
    try {
      const result = await answerClarification(
        state.current.question,
        state.current.clarification.items,
        answers,
      );
      dispatch({ type: "TURN_COMPLETED", result });
    } catch (error) {
      dispatch({ type: "REQUEST_FAILED", message: describeError(error) });
    }
  }

  const isBusy = state.phase === "submitting" || state.phase === "submitting_answer";
  const showClarificationForm =
    state.current?.clarification !== undefined &&
    (state.phase === "needs_clarification" || state.phase === "submitting_answer");

  return (
    <div className="app">
      <h1>AIJudge</h1>
      {state.error && (
        <div className="error-banner" role="alert">
          <span>{state.error}</span>
          <button type="button" onClick={() => dispatch({ type: "ERROR_DISMISSED" })}>
            Dismiss
          </button>
        </div>
      )}
      <ChatHistory turns={state.history} />
      {showClarificationForm && state.current?.clarification ? (
        <ClarificationForm
          items={state.current.clarification.items}
          onSubmit={handleClarificationSubmit}
          disabled={isBusy}
        />
      ) : (
        <QuestionInput onSubmit={handleAsk} disabled={isBusy} />
      )}
    </div>
  );
}
```

Append to `frontend/src/App.css`:
```css
.error-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #fdecea;
  border: 1px solid #f5c6cb;
  border-radius: 0.5rem;
  padding: 0.5rem 1rem;
  margin-bottom: 1rem;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npm test` (from `frontend/`)
Expected: PASS — all `App.test.tsx` cases, plus every prior task's tests, still pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.css frontend/test/App.test.tsx
git commit -m "feat(frontend): wire App to the ask/clarify/answer flow end-to-end"
```

---

## Task 9: Dev workflow docs and env template

**Files:**
- Create: `frontend/.env.example`
- Modify: `README.md`

**Interfaces:**
- None (documentation only).

- [ ] **Step 1: Add the env template**

`frontend/.env.example`:
```
VITE_AIJUDGE_API_URL=http://localhost:8000
```

- [ ] **Step 2: Document the dev workflow in the root README**

Add a new section to `README.md` (after the existing setup/run instructions):
```markdown
## Running the frontend

The React chat UI lives in `frontend/` and talks to the API service (`python -m aijudge.api`) over HTTP.

1. Start the backend: `python -m aijudge.api` (defaults to `http://localhost:8000`).
2. In a separate terminal:
   ```
   cd frontend
   npm install
   cp .env.example .env   # first time only; override VITE_AIJUDGE_API_URL if the backend isn't on the default host/port
   npm run dev
   ```
3. Open the URL Vite prints (default `http://localhost:5173`).

Run the frontend's test suite with `npm test` from `frontend/`.
```

- [ ] **Step 3: Verify the full stack manually**

Run: `python -m aijudge.api` in one terminal, `cd frontend && npm run dev` in another, then open the printed
URL in a browser and ask a real question end-to-end (e.g. "What does Effect Veiler do?").
Expected: the question is answered (or triggers clarification) using the real backend, matching the behavior
verified by the automated tests in Tasks 1-8.

- [ ] **Step 4: Commit**

```bash
git add frontend/.env.example README.md
git commit -m "docs: document the frontend dev workflow"
```

---

## Self-Review Notes

- **Spec coverage:** stack/repo layout (Task 1), API client + types (Task 2), state machine (Task 3), each
  component (Tasks 4-7), full wiring including error handling and the `disambiguate_card` path (Task 8), and the
  dev workflow doc (Task 9) all map directly to sections of
  `docs/superpowers/specs/2026-09-11-frontend-chat-ui-design.md`. Production build/deployment and the deferred
  card-browser/admin views are out of scope per that spec and are not tasked here.
- **Type consistency:** `ClarificationItem`, `Citation`, `ResultResponse`, `NeedsClarificationResponse`,
  `QuestionResponse` (Task 2) are used identically by name in Tasks 3-8; `Turn`, `ChatState`, `ChatAction`,
  `chatReducer`, `initialChatState` (Task 3) are used identically by name in Tasks 7-8; component prop names
  (`onSubmit`, `disabled`, `items`, `result`, `turns`) match between each component's definition task and its
  usage in Task 8.
- **No placeholders:** every step includes complete, runnable code — no TBD/TODO markers or "similar to Task N"
  references.
