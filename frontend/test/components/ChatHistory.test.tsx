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
    expect(screen.getByText("— My turn")).toBeInTheDocument();
    expect(screen.getByText("Yes, on your turn it works.")).toBeInTheDocument();
  });
});
