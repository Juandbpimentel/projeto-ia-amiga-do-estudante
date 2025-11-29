"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ChatMessage } from "@/types/chat";

interface ChatMessageProps {
  message: ChatMessage;
}

export function ChatMessageBubble({ message }: ChatMessageProps) {
  const isUser = message.role === "user";

  return (
    <div
      className={`chat-row ${isUser ? "chat-row-user" : "chat-row-assistant"}`}
    >
      <div
        className={`chat-bubble ${
          isUser ? "chat-bubble-user" : "chat-bubble-assistant"
        }`}
      >
        {isUser ? (
          <p>{message.content}</p>
        ) : (
          <div className="chat-markdown">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                p: ({ children }) => <p>{children}</p>,
                ul: ({ children }) => <ul>{children}</ul>,
                ol: ({ children }) => <ol>{children}</ol>,
                li: ({ children }) => <li>{children}</li>,
              }}
            >
              {message.content}
            </ReactMarkdown>
          </div>
        )}
        <span className="chat-timestamp">
          {new Date(message.createdAt).toLocaleTimeString("pt-BR", {
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
      </div>
    </div>
  );
}
