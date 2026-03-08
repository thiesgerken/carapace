"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUp, Clock, Square } from "lucide-react";
import { cn } from "@/lib/utils";
import type { SlashCommand } from "@/lib/api";

interface ChatInputProps {
  onSend: (content: string) => void;
  onCancel?: () => void;
  onInterrupt?: (content: string) => void;
  connected: boolean;
  waiting?: boolean;
  hasQueuedMessage?: boolean;
  commands?: SlashCommand[];
}

export function ChatInput({
  onSend,
  onCancel,
  onInterrupt,
  connected,
  waiting,
  hasQueuedMessage,
  commands = [],
}: ChatInputProps) {
  const [value, setValue] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // Show autocomplete when input starts with "/" and is a single word, but not if it exactly matches a command
  const exactMatch = commands.some((c) => c.command === value.trim().toLowerCase());
  const showMenu = value.startsWith("/") && !value.includes(" ") && !exactMatch;

  const filtered = useMemo(() => {
    if (!showMenu) return [];
    const prefix = value.toLowerCase();
    return commands.filter((c) => c.command.startsWith(prefix));
  }, [value, showMenu, commands]);

  // Scroll selected item into view
  useEffect(() => {
    if (!menuRef.current) return;
    const item = menuRef.current.children[selectedIndex] as HTMLElement | undefined;
    item?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex]);

  const selectCommand = useCallback(
    (cmd: string) => {
      setValue(cmd);
      textareaRef.current?.focus();
    },
    [],
  );

  const clearInput = useCallback(() => {
    setValue("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, []);

  const submit = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || !connected) return;
    if (waiting && hasQueuedMessage) return;
    onSend(trimmed);
    clearInput();
  }, [value, connected, waiting, hasQueuedMessage, onSend, clearInput]);

  const interrupt = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || !connected || !waiting || hasQueuedMessage) return;
    onInterrupt?.(trimmed);
    clearInput();
  }, [value, connected, waiting, hasQueuedMessage, onInterrupt, clearInput]);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (showMenu && filtered.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((i) => (i + 1) % filtered.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((i) => (i - 1 + filtered.length) % filtered.length);
        return;
      }
      if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) {
        e.preventDefault();
        selectCommand(filtered[selectedIndex].command);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setValue("");
        return;
      }
    } else if (e.key === "Enter" && !e.shiftKey && !e.altKey) {
      e.preventDefault();
      submit();
    } else if (e.key === "Enter" && e.altKey && !e.shiftKey) {
      e.preventDefault();
      interrupt();
    }
  }

  function handleInput(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setValue(e.target.value);
    setSelectedIndex(0);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  }

  const hasText = value.trim().length > 0;

  let tooltip: string;
  if (!waiting) {
    tooltip = "Send message (Enter)";
  } else if (hasText) {
    tooltip = "Enter to queue · ⌥Enter to interrupt · Click to stop";
  } else {
    tooltip = "Stop generation";
  }

  return (
    <div className="border-t border-border bg-background px-4 py-3">
      {hasQueuedMessage && (
        <div className="mx-auto max-w-3xl mb-2 flex items-center gap-1.5 text-xs text-muted-foreground">
          <Clock className="h-3 w-3" />
          <span>Message queued — will be sent when the agent finishes</span>
        </div>
      )}
      <div className="relative mx-auto max-w-3xl">
        {/* Slash command autocomplete menu */}
        {showMenu && filtered.length > 0 && (
          <div
            ref={menuRef}
            className={cn(
              "absolute bottom-full left-0 right-0 z-50 mb-1 max-h-60 overflow-y-auto",
              "rounded-xl border border-border bg-background shadow-lg",
              "py-1",
            )}
          >
            {filtered.map((cmd, i) => (
              <button
                key={cmd.command}
                type="button"
                onMouseDown={(e) => {
                  e.preventDefault(); // keep textarea focused
                  selectCommand(cmd.command);
                }}
                onMouseEnter={() => setSelectedIndex(i)}
                className={cn(
                  "flex w-full items-baseline gap-3 px-3 py-1.5 text-left text-sm",
                  "transition-colors",
                  i === selectedIndex
                    ? "bg-accent text-accent-foreground"
                    : "text-foreground hover:bg-accent/50",
                )}
              >
                <span className="font-mono text-xs font-medium shrink-0">
                  {cmd.command}
                </span>
                <span className="text-xs text-muted-foreground truncate">
                  {cmd.description}
                </span>
              </button>
            ))}
          </div>
        )}

        <div
          className={cn(
            "flex items-end gap-2",
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
            disabled={!connected}
            rows={1}
            className={cn(
              "flex-1 resize-none bg-transparent text-sm outline-none",
              "placeholder:text-muted-foreground/50",
              "disabled:opacity-50",
            )}
          />
          <button
            onClick={waiting ? onCancel : submit}
            disabled={waiting ? false : !connected || !hasText}
            title={tooltip}
            className={cn(
              "shrink-0 rounded-lg p-1.5 transition-colors",
              waiting
                ? "bg-destructive/60 text-destructive-foreground hover:bg-destructive/75"
                : "bg-foreground text-background hover:bg-foreground/90",
              "disabled:opacity-30 disabled:cursor-not-allowed",
            )}
          >
            {waiting ? (
              <Square className="h-4 w-4" />
            ) : (
              <ArrowUp className="h-4 w-4" />
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
