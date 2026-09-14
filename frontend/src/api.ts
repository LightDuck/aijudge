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
