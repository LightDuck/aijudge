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
