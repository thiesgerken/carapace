"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUp, Clock, Square } from "lucide-react";
import { cn } from "@/lib/utils";
import type { SlashCommand } from "@/lib/api";
import type { TurnUsage } from "@/lib/types";

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

const MODEL_COMMANDS = ["/model", "/model-sentinel", "/model-title"];

interface ChatInputProps {
  onSend: (content: string) => void;
  onCancel?: () => void;
  onInterrupt?: (content: string) => void;
  connected: boolean;
  waiting?: boolean;
  queuedMessage?: string | null;
  commands?: SlashCommand[];
  availableModels?: string[];
  usage?: TurnUsage | null;
}

export function ChatInput({
  onSend,
  onCancel,
  onInterrupt,
  connected,
  waiting,
  queuedMessage,
  commands = [],
  availableModels = [],
  usage,
}: ChatInputProps) {
  const [value, setValue] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // Focus textarea on mount (e.g. when a new session is created).
  // Skip on touch devices — programmatic focus opens the keyboard but the
  // browser won't scroll the input into view, leaving it hidden.
  useEffect(() => {
    const isTouch = window.matchMedia("(pointer: coarse)").matches;
    if (!isTouch) {
      textareaRef.current?.focus();
    }
  }, []);

  // Show autocomplete when input starts with "/" and is a single word, but not if it exactly matches a command
  const exactMatch = commands.some((c) => c.command === value.trim().toLowerCase());
  const showMenu = value.startsWith("/") && !value.includes(" ") && !exactMatch;

  const filtered = useMemo(() => {
    if (!showMenu) return [];
    const prefix = value.toLowerCase();
    return commands.filter((c) => c.command.startsWith(prefix));
  }, [value, showMenu, commands]);

  // Model argument autocomplete for /model, /model-sentinel, /model-title
  const modelSuggestions = useMemo((): { items: string[]; prefix: string } => {
    const lower = value.toLowerCase();
    const match = MODEL_COMMANDS.find((c) => lower.startsWith(c + " "));
    if (!match) return { items: [], prefix: "" };

    const afterCmd = value.slice(match.length + 1);
    const partial = afterCmd.trimStart().toLowerCase();

    // Don't show suggestions if there's already a complete argument with space after
    if (afterCmd.trimEnd().includes(" ")) return { items: [], prefix: "" };

    const suggestions = availableModels.filter((m) => m.toLowerCase().startsWith(partial));
    return { items: suggestions, prefix: afterCmd };
  }, [value, availableModels]);

  const showModelMenu = modelSuggestions.items.length > 0;

  const selectModelSuggestion = useCallback(
    (item: string) => {
      const prefix = value.slice(0, value.length - modelSuggestions.prefix.length);
      setValue(prefix + item);
      textareaRef.current?.focus();
    },
    [value, modelSuggestions.prefix],
  );

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
    if (waiting && queuedMessage) return;
    onSend(trimmed);
    clearInput();
  }, [value, connected, waiting, queuedMessage, onSend, clearInput]);

  const interrupt = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || !connected || !waiting || !!queuedMessage) return;
    onInterrupt?.(trimmed);
    clearInput();
  }, [value, connected, waiting, queuedMessage, onInterrupt, clearInput]);

  function handleKeyDown(e: React.KeyboardEvent) {
    const activeMenu = showMenu ? "commands" : showModelMenu ? "models" : null;
    const menuLength = activeMenu === "commands" ? filtered.length : activeMenu === "models" ? modelSuggestions.items.length : 0;

    if (activeMenu && menuLength > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((i) => (i + 1) % menuLength);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((i) => (i - 1 + menuLength) % menuLength);
        return;
      }
      if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) {
        e.preventDefault();
        if (activeMenu === "commands") {
          selectCommand(filtered[selectedIndex].command);
        } else {
          selectModelSuggestion(modelSuggestions.items[selectedIndex]);
        }
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
      {queuedMessage && (
        <div className="mx-auto max-w-3xl mb-2 flex items-center gap-1.5 text-xs text-muted-foreground">
          <Clock className="h-3 w-3" />
          <span className="truncate">Queued: {queuedMessage}</span>
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

        {/* Model argument autocomplete menu */}
        {showModelMenu && (
          <div
            ref={menuRef}
            className={cn(
              "absolute bottom-full left-0 right-0 z-50 mb-1 max-h-60 overflow-y-auto",
              "rounded-xl border border-border bg-background shadow-lg",
              "py-1",
            )}
          >
            {modelSuggestions.items.map((item, i) => (
              <button
                key={item}
                type="button"
                onMouseDown={(e) => {
                  e.preventDefault();
                  selectModelSuggestion(item);
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
                  {item}
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
            rows={1}
            className={cn(
              "flex-1 resize-none bg-transparent text-base sm:text-sm outline-none",
              "placeholder:text-muted-foreground/50",
            )}
          />
          <button
            onClick={waiting ? onCancel : submit}
            disabled={waiting ? false : !connected || !hasText}
            title={tooltip}
            className={cn(
              "shrink-0 rounded-lg p-2 transition-colors",
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
          <TokenGauge usage={usage} onClickUsage={connected && !waiting ? () => onSend("/usage") : undefined} />
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
