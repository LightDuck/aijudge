import type { ResultResponse, ResultStatus } from "../types";

interface MessageBubbleProps {
  result: ResultResponse;
}

const BANNER_CLASS_BY_STATUS: Record<Exclude<ResultStatus, "answer">, string> = {
  escalate: "message-bubble message-bubble--escalate",
  not_supported: "message-bubble message-bubble--not-supported",
  off_topic: "message-bubble message-bubble--off-topic",
};

function bannerClassFor(status: Exclude<ResultStatus, "answer">): string {
  switch (status) {
    case "escalate":
    case "not_supported":
    case "off_topic":
      return BANNER_CLASS_BY_STATUS[status];
    default: {
      const _exhaustive: never = status;
      throw new Error(`Unhandled result status: ${_exhaustive}`);
    }
  }
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

  return (
    <div className={bannerClassFor(result.status)} role="status">
      <p>{result.text}</p>
    </div>
  );
}
