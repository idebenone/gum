import type { ChatResponse } from "@/lib/types/chat";

interface ChatResponsesProps {
  responses: ChatResponse[];
}

export default function ChatResponsesComponent({
  responses,
}: ChatResponsesProps) {
  return (
    <div>
      {responses.map((response) => (
        <div
          key={response.id}
          className={`my-2 p-2 rounded-xl ${
            response.sender === "user"
              ? "border border-muted self-end"
              : "bg-gray-200 self-start"
          } max-w-[80%]`}
        >
          <p className="whitespace-pre-wrap">{response.content}</p>
          <span className="text-xs text-gray-500">
            {new Date(response.timestamp).toLocaleTimeString()}
          </span>
        </div>
      ))}
    </div>
  );
}
