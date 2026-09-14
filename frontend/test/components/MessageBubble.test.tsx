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

  it("renders an off_topic result in its own distinct banner style", () => {
    render(
      <MessageBubble
        result={{ status: "off_topic", text: "I only answer Yu-Gi-Oh! rules questions.", citations: null }}
      />,
    );

    const banner = screen.getByRole("status");
    expect(banner).toHaveClass("message-bubble--off-topic");
    expect(banner).not.toHaveClass("message-bubble--not-supported");
    expect(banner).not.toHaveClass("message-bubble--escalate");
    expect(banner).toHaveTextContent("I only answer Yu-Gi-Oh! rules questions.");
  });
});
