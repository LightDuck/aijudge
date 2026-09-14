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
