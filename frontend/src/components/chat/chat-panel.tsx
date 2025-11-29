"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChatMessage } from "../../types/chat";
import { sendChatMessage, startChat } from "@/lib/api";
import { ChatMessageBubble } from "./chat-message";
import { ChatInput } from "./chat-input";

function createId() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }

  return Math.random().toString(36).slice(2);
}

export function ChatPanel() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [isBooting, setIsBooting] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const endRef = useRef<HTMLDivElement | null>(null);

  const scrollToBottom = useCallback(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    // Auto-clear errors after 10 seconds for a better UX.
    if (!error) return;
    const timer = setTimeout(() => setError(null), 5000);
    return () => clearTimeout(timer);
  }, [error]);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  const bootChat = useCallback(async () => {
    setIsBooting(true);
    setError(null);
    setMessages([]);
    setSessionId(null);

    try {
      const data = await startChat();
      console.debug("[ChatPanel] startChat response:", data);
      setSessionId(data.session_id);
      console.debug("[ChatPanel] sessionId set:", data.session_id);
      setMessages([
        {
          id: createId(),
          role: "assistant",
          content: data.message,
          createdAt: new Date().toISOString(),
        },
      ]);
    } catch (err) {
      const message =
        err instanceof Error
          ? err.message
          : "Erro inesperado ao iniciar o chat.";
      setError(message);
      const systemId = createId();
      setMessages((prev) => [
        ...prev,
        {
          id: systemId,
          role: "system",
          content:
            "Falha ao iniciar o chat. Tente novamente em alguns instantes.",
          createdAt: new Date().toISOString(),
        },
      ]);
      setTimeout(() => {
        setMessages((prev) => prev.filter((m) => m.id !== systemId));
      }, 10000);
    } finally {
      setIsBooting(false);
    }
  }, []);

  useEffect(() => {
    bootChat();
  }, [bootChat]);

  const handleSend = useCallback(async () => {
    if (!sessionId || !inputValue.trim() || isSending) {
      return;
    }

    const userMessage: ChatMessage = {
      id: createId(),
      role: "user",
      content: inputValue.trim(),
      createdAt: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputValue("");
    setIsSending(true);
    setError(null);

    try {
      console.debug(
        "[ChatPanel] sendChatMessage request: sessionId=",
        sessionId,
        "message=",
        userMessage.content
      );
      const response = await sendChatMessage(sessionId, userMessage.content);
      console.debug("[ChatPanel] sendChatMessage response:", response);
      const content = response.selected_query
        ? `${response.message}\n\n🔍 Consulta confirmada: ${response.selected_query}`
        : response.message;

      const assistantMessage: ChatMessage = {
        id: createId(),
        role: "assistant",
        content,
        createdAt: new Date().toISOString(),
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Erro ao enviar a mensagem.";
      setError(message);
      const systemId = createId();
      setMessages((prev) => [
        ...prev,
        {
          id: systemId,
          role: "system",
          content: "Não foi possível falar com o assistente. Tente novamente.",
          createdAt: new Date().toISOString(),
        },
      ]);
      // auto-remove the system error message after 10 seconds
      setTimeout(() => {
        setMessages((prev) => prev.filter((m) => m.id !== systemId));
      }, 10000);
    } finally {
      setIsSending(false);
    }
  }, [inputValue, isSending, sessionId]);

  const placeholder = useMemo(() => {
    if (!sessionId) {
      return "Aguarde o assistente ficar disponível...";
    }
    return "Pergunte sobre feriados, cardápio, professores...";
  }, [sessionId]);

  return (
    <section className="chat-panel">
      <header className="chat-header">
        <div>
          <p className="chat-title">Assistente UFC Quixadá</p>
          <p className="chat-subtitle">
            Consulte rapidamente cardápios, feriados e status dos sistemas
          </p>
        </div>
        <button className="chat-reset" disabled={isBooting} onClick={bootChat}>
          Reiniciar chat
        </button>
      </header>

      {error && <p className="chat-error">{error}</p>}

      <div className="chat-messages">
        {isBooting && (
          <p className="chat-info">Configurando o atendimento...</p>
        )}
        {!isBooting && messages.length === 0 && (
          <p className="chat-info">Envie uma mensagem para começar.</p>
        )}
        {messages.map((message) => (
          <ChatMessageBubble key={message.id} message={message} />
        ))}
        <div ref={endRef} />
      </div>

      <ChatInput
        value={inputValue}
        onChange={setInputValue}
        onSubmit={handleSend}
        placeholder={placeholder}
        disabled={!sessionId || isBooting || isSending}
      />
    </section>
  );
}
