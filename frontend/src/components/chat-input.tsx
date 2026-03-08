"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUp, Square } from "lucide-react";
import { cn } from "@/lib/utils";
import type { SlashCommand } from "@/lib/api";
import type { TurnUsage } from "@/lib/types";

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

interface ChatInputProps {
  onSend: (content: string) => void;
  onCancel?: () => void;
  disabled?: boolean;
  waiting?: boolean;
  commands?: SlashCommand[];
  usage?: TurnUsage | null;
}

export function ChatInput({ onSend, onCancel, disabled, waiting, commands = [], usage }: ChatInputProps) {
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
    } else if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  function handleInput(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setValue(e.target.value);
    setSelectedIndex(0);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  }

  return (
    <div className="border-t border-border bg-background px-4 py-3">
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
            disabled={disabled}
            rows={1}
            className={cn(
              "flex-1 resize-none bg-transparent text-sm outline-none",
              "placeholder:text-muted-foreground/50",
              "disabled:opacity-50",
            )}
          />
          <button
            onClick={waiting ? onCancel : submit}
            disabled={waiting ? false : disabled || !value.trim()}
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

        {/* Token usage gauge */}
        {usage && (usage.input_tokens > 0 || usage.output_tokens > 0) && (
          <TokenGauge usage={usage} onClickUsage={!disabled && !waiting ? () => onSend("/usage") : undefined} />
        )}
      </div>
    </div>
  );
}

/** Compact context-window gauge rendered below the input box. */
function TokenGauge({ usage, onClickUsage }: { usage: TurnUsage; onClickUsage?: () => void }) {
  const total = usage.input_tokens + usage.output_tokens;
  // Context window limits for common models; 200k is a safe default
  const cap = 200_000;
  const pct = Math.min((usage.input_tokens / cap) * 100, 100);

  // Color shifts from muted → yellow → red as context fills up
  const barColor =
    pct > 75
      ? "bg-destructive/70"
      : pct > 50
        ? "bg-warning/70"
        : "bg-muted-foreground/30";

  const tooltip = `${formatTokens(total)} / 200k context window tokens used\nClick for detailed usage breakdown`;

  return (
    <div className="mt-1.5 flex items-center gap-2 px-1">
      <div className="h-1 flex-1 rounded-full bg-muted overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all", barColor)}
          style={{ width: `${pct}%` }}
        />
      </div>
      <button
        type="button"
        onClick={onClickUsage}
        disabled={!onClickUsage}
        title={tooltip}
        className={cn(
          "shrink-0 text-[10px] tabular-nums text-muted-foreground",
          onClickUsage && "hover:text-foreground cursor-pointer transition-colors",
          !onClickUsage && "cursor-default",
        )}
      >
        {formatTokens(total)} tokens
      </button>
    </div>
  );
}
