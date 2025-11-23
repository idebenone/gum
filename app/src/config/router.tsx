import AuthPage from "@/pages/auth";
import ChatPage from "@/pages/chat";

export const routes = [
  { path: "/", element: <ChatPage /> },
  { path: "/auth", element: <AuthPage /> },
];
