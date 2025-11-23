export type ChatResponse = {
  id: string;
  content: string;
  sender: "system" | "user";
  timestamp: string;
};
