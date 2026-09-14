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
