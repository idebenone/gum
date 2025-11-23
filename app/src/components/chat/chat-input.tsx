import { Textarea } from "../ui/textarea";

interface ChatInputProps {
  text: string;
  setText: (text: string) => void;
  onSubmit: () => void;
}

export default function ChatInputComponent({
  text,
  setText,
  onSubmit,
}: ChatInputProps) {
  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && text.trim() !== "") {
      e.preventDefault();
      setText("");
      onSubmit();
    }
  }

  return (
    <div>
      <Textarea
        placeholder="Share your thoughts..."
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDownCapture={handleKeyDown}
      />
    </div>
  );
}
