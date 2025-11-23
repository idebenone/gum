import ChatInputComponent from "@/components/chat/chat-input";
import ChatResponsesComponent from "@/components/chat/chat-responses";
import type { ChatResponse } from "@/lib/types/chat";
import { useState } from "react";

export default function ChatPage() {
  const [inputText, setInputText] = useState<string>("");
  const [responses, setResponses] = useState<ChatResponse[]>([]);
  const [filteredResponses, setFilteredResponses] = useState<ChatResponse[]>([]);

  async function handleSubmit() {
    setResponses([
      ...responses,
      {
        content: inputText,
        id: crypto.randomUUID(),
        sender: "user",
        timestamp: new Date().toISOString(),
      },
    ]);
  }

  return (
    <div className="h-full w-full flex justify-center">
      <div className="flex flex-col justify-between w-full p-2 lg:w-1/2">
        <ChatResponsesComponent responses={responses} filteredResponses={filteredResponses} inputText={inputText} />
        <ChatInputComponent
          text={inputText}
          setText={(e) => {
            setInputText(e);
            const filtered = responses.filter((r) =>
              r.content.toLowerCase().includes(e.toLowerCase())
            ); setFilteredResponses(filtered);
          }}
          onSubmit={handleSubmit}
        />
      </div>
    </div>
  );
}
