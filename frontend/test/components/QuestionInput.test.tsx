import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import QuestionInput from "../../src/components/QuestionInput";

describe("QuestionInput", () => {
  it("submits the trimmed question and clears the input", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<QuestionInput onSubmit={onSubmit} disabled={false} />);

    await user.type(screen.getByLabelText("Question"), "  Does X negate Y?  ");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    expect(onSubmit).toHaveBeenCalledWith("Does X negate Y?");
    expect(screen.getByLabelText("Question")).toHaveValue("");
  });

  it("does not submit a blank question", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<QuestionInput onSubmit={onSubmit} disabled={false} />);

    await user.type(screen.getByLabelText("Question"), "   ");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("disables the input and button when disabled is true", () => {
    render(<QuestionInput onSubmit={vi.fn()} disabled={true} />);

    expect(screen.getByLabelText("Question")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
  });
});
