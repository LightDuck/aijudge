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

  it("shows the in-flight question and a thinking indicator while a request is pending", async () => {
    let resolveAsk: (value: Awaited<ReturnType<typeof askQuestion>>) => void;
    const pending = new Promise<Awaited<ReturnType<typeof askQuestion>>>((resolve) => {
      resolveAsk = resolve;
    });
    vi.mocked(askQuestion).mockReturnValue(pending);
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByLabelText("Question"), "Does Effect Veiler negate X?");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    expect(screen.getByText("Does Effect Veiler negate X?")).toBeInTheDocument();
    expect(screen.getByText("Thinking…")).toBeInTheDocument();

    resolveAsk!({
      status: "answer",
      text: "Yes, it negates the activation.",
      citations: [],
    });

    expect(await screen.findByText("Yes, it negates the activation.")).toBeInTheDocument();
    expect(screen.queryByText("Thinking…")).not.toBeInTheDocument();
  });

  it("shows an off_topic result in its distinct banner", async () => {
    vi.mocked(askQuestion).mockResolvedValue({
      status: "off_topic",
      text: "I only answer Yu-Gi-Oh! rules questions.",
      citations: null,
    });
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByLabelText("Question"), "What's the weather today?");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    const banner = await screen.findByRole("status");
    expect(banner).toHaveClass("message-bubble--off-topic");
    expect(banner).toHaveTextContent("I only answer Yu-Gi-Oh! rules questions.");
  });

  it("keeps the original question visible while answering a clarification exchange", async () => {
    let resolveAsk: (value: Awaited<ReturnType<typeof askQuestion>>) => void;
    const pending = new Promise<Awaited<ReturnType<typeof askQuestion>>>((resolve) => {
      resolveAsk = resolve;
    });
    vi.mocked(askQuestion).mockReturnValue(pending);
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByLabelText("Question"), "Does X work during my turn?");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    resolveAsk!({
      status: "needs_clarification",
      question: "Does X work during my turn?",
      items: [{ kind: "clarify", text: "Whose turn is it?" }],
    });

    expect(await screen.findByLabelText("Whose turn is it?")).toBeInTheDocument();
    expect(screen.getByText("Does X work during my turn?")).toBeInTheDocument();
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
