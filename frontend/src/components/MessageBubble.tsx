import type { ResultResponse } from "../types";

interface MessageBubbleProps {
  result: ResultResponse;
}

export default function MessageBubble({ result }: MessageBubbleProps) {
  if (result.status === "answer") {
    return (
      <div className="message-bubble message-bubble--answer">
        <p>{result.text}</p>
        {result.citations && result.citations.length > 0 && (
          <ul className="message-bubble__citations">
            {result.citations.map((citation, index) => (
              <li key={index}>
                <strong>{citation.label}:</strong> {citation.text}
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  const bannerClass =
    result.status === "escalate"
      ? "message-bubble message-bubble--escalate"
      : "message-bubble message-bubble--not-supported";

  return (
    <div className={bannerClass} role="status">
      <p>{result.text}</p>
    </div>
  );
}
