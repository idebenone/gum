import type { ChatResponse } from "@/lib/types/chat";

interface ChatResponsesProps {
  responses: ChatResponse[];
  filteredResponses?: ChatResponse[];
}

export default function ChatResponsesComponent({
  responses,
  filteredResponses,
  inputText, // pass the current input text
}: ChatResponsesProps & { inputText: string }) {

  return (
    <div className="overflow-y-scroll">
      <div className="p-4 columns-4 gap-2 [column-fill:balance]">
        {responses.map((response) => {
          const isMatch =
            inputText && filteredResponses
              ? filteredResponses.some((r) => r.id === response.id)
              : false;

          return (
            <div
              key={response.id}
              className={`
                break-inside-avoid mb-2 inline-block w-full p-3 rounded-xl border shadow-sm animate-chat-bubble
                transition-all duration-300
                ${isMatch ? "bg-muted opacity-100" : inputText ? "opacity-30 blur-[1px]" : "opacity-100"}
              `}
            >
              <p className="whitespace-pre-wrap line-clamp-6">
                {response.content}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

