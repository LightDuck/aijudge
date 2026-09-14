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
