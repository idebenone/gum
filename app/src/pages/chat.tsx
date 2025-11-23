import ChatInputComponent from "@/components/chat/chat-input";
import ChatResponsesComponent from "@/components/chat/chat-responses";
import type { ChatResponse } from "@/lib/types/chat";
import { useState } from "react";

export default function ChatPage() {
  const [inputText, setInputText] = useState<string>("");
  const [responses, setResponses] = useState<ChatResponse[]>([]);

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
        <ChatResponsesComponent responses={responses} />
        <ChatInputComponent
          text={inputText}
          setText={setInputText}
          onSubmit={handleSubmit}
        />
      </div>
    </div>
  );
}
