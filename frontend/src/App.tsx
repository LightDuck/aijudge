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
  const turns = state.current ? [...state.history, state.current] : state.history;

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
      <ChatHistory turns={turns} />
      {isBusy && <p className="thinking-indicator">Thinking…</p>}
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
