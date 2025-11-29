"use client";

import { FormEvent, KeyboardEvent } from "react";

interface ChatInputProps {
  value: string;
  placeholder?: string;
  disabled?: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
}

export function ChatInput({
  value,
  disabled,
  placeholder,
  onChange,
  onSubmit,
}: ChatInputProps) {
  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onSubmit();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // Send when Enter is pressed without Shift (Shift+Enter inserts newline)
    if (event.key === "Enter" && !event.shiftKey) {
      // Prevent default newline behavior
      event.preventDefault();
      // Don't submit if disabled or whitespace only
      if (disabled || !value.trim()) return;
      onSubmit();
    }
  };

  return (
    <form className="chat-input" onSubmit={handleSubmit}>
      <textarea
        className="chat-textarea"
        placeholder={placeholder}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        rows={2}
      />
      <button
        className="chat-send"
        type="submit"
        disabled={disabled || !value.trim()}
      >
        Enviar
      </button>
    </form>
  );
}
