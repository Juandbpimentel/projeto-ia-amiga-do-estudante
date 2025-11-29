export type ChatRole = "assistant" | "user" | "system";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  createdAt: string;
}

export interface StartChatResponse {
  session_id: string;
  message: string;
}

export interface BackendChatResponse {
  message: string;
  selected_query?: string;
}
