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
