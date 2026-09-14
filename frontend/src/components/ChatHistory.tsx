import type { Turn } from "../reducer";
import MessageBubble from "./MessageBubble";

interface ChatHistoryProps {
  turns: Turn[];
}

export default function ChatHistory({ turns }: ChatHistoryProps) {
  return (
    <div className="chat-history">
      {turns.map((turn, index) => (
        <div key={index} className="chat-history__turn">
          <p className="chat-history__question">{turn.question}</p>
          {turn.clarification && (
            <div className="chat-history__clarification">
              {turn.clarification.items.map((item, itemIndex) => {
                const answer = turn.clarification!.answers[itemIndex];
                return (
                  <p key={itemIndex} className="chat-history__clarification-item">
                    <em>{item.text}</em>
                    {answer && <span> — {answer}</span>}
                  </p>
                );
              })}
            </div>
          )}
          {turn.result && <MessageBubble result={turn.result} />}
        </div>
      ))}
    </div>
  );
}
