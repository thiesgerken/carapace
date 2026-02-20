"use client";

import { useCallback, useRef, useState } from "react";
import { ArrowUp } from "lucide-react";
import { cn } from "@/lib/utils";

interface ChatInputProps {
  onSend: (content: string) => void;
  disabled?: boolean;
}

export function ChatInput({ onSend, disabled }: ChatInputProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const submit = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [value, disabled, onSend]);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  function handleInput(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setValue(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  }

  return (
    <div className="border-t border-border bg-background px-4 py-3">
      <div
        className={cn(
          "mx-auto flex max-w-3xl items-end gap-2",
          "rounded-xl border border-border bg-muted/30 px-3 py-2",
          "focus-within:ring-2 focus-within:ring-ring/30 focus-within:border-ring",
          "transition-colors",
        )}
      >
        <textarea
          ref={textareaRef}
          value={value}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder="Message Carapace…"
          disabled={disabled}
          rows={1}
          className={cn(
            "flex-1 resize-none bg-transparent text-sm outline-none",
            "placeholder:text-muted-foreground/50",
            "disabled:opacity-50",
          )}
        />
        <button
          onClick={submit}
          disabled={disabled || !value.trim()}
          className={cn(
            "shrink-0 rounded-lg p-1.5 transition-colors",
            "bg-foreground text-background",
            "hover:bg-foreground/90",
            "disabled:opacity-30 disabled:cursor-not-allowed",
          )}
        >
          <ArrowUp className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
