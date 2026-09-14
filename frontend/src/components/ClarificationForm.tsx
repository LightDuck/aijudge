import { useState } from "react";
import type { FormEvent } from "react";
import type { ClarificationItem } from "../types";

interface ClarificationFormProps {
  items: ClarificationItem[];
  onSubmit: (answers: string[]) => void;
  disabled: boolean;
}

export default function ClarificationForm({ items, onSubmit, disabled }: ClarificationFormProps) {
  const [answers, setAnswers] = useState<string[]>(() => items.map(() => ""));

  function handleChange(index: number, value: string) {
    setAnswers((prev) => prev.map((answer, i) => (i === index ? value : answer)));
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit(answers);
  }

  return (
    <form onSubmit={handleSubmit} className="clarification-form">
      {items.map((item, index) => (
        <label key={index} className="clarification-form__item">
          <span>{item.text}</span>
          <input
            type="text"
            value={answers[index]}
            onChange={(event) => handleChange(index, event.target.value)}
            disabled={disabled}
            aria-label={item.text}
          />
        </label>
      ))}
      <button type="submit" disabled={disabled}>
        Submit
      </button>
    </form>
  );
}
