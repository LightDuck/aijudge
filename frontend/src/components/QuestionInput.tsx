import { useState } from "react";
import type { FormEvent } from "react";

interface QuestionInputProps {
  onSubmit: (question: string) => void;
  disabled: boolean;
}

export default function QuestionInput({ onSubmit, disabled }: QuestionInputProps) {
  const [value, setValue] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = value.trim();
    if (!trimmed) {
      return;
    }
    onSubmit(trimmed);
    setValue("");
  }

  return (
    <form onSubmit={handleSubmit} className="question-input">
      <input
        type="text"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder="Ask a Yu-Gi-Oh! rules question..."
        disabled={disabled}
        aria-label="Question"
      />
      <button type="submit" disabled={disabled}>
        Ask
      </button>
    </form>
  );
}
