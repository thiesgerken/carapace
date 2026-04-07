"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUp, Clock, Square } from "lucide-react";
import { cn } from "@/lib/utils";
import type { AvailableModelInfo, SlashCommand } from "@/lib/api";
import type { TurnUsage, TurnUsageBreakdownPct } from "@/lib/types";

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
  availableModelEntries?: AvailableModelInfo[];
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
  availableModelEntries = [],
  usage,
}: ChatInputProps) {
  const [value, setValue] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const availableModelIds = useMemo(
    () => availableModelEntries.map((e) => e.id),
    [availableModelEntries],
  );

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
  const exactMatch = commands.some(
    (c) => c.command === value.trim().toLowerCase(),
  );
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

    // Don't show if the argument already exactly matches a model
    if (availableModelIds.some((m) => m.toLowerCase() === partial))
      return { items: [], prefix: "" };

    const suggestions = availableModelIds.filter((m) =>
      m.toLowerCase().startsWith(partial),
    );
    return { items: suggestions, prefix: afterCmd };
  }, [value, availableModelIds]);

  const showModelMenu = modelSuggestions.items.length > 0;

  const selectModelSuggestion = useCallback(
    (item: string) => {
      const prefix = value.slice(
        0,
        value.length - modelSuggestions.prefix.length,
      );
      setValue(prefix + item);
      textareaRef.current?.focus();
    },
    [value, modelSuggestions.prefix],
  );

  // Scroll selected item into view
  useEffect(() => {
    if (!menuRef.current) return;
    const item = menuRef.current.children[selectedIndex] as
      | HTMLElement
      | undefined;
    item?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex]);

  const selectCommand = useCallback((cmd: string) => {
    setValue(cmd);
    textareaRef.current?.focus();
  }, []);

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
    const menuLength =
      activeMenu === "commands"
        ? filtered.length
        : activeMenu === "models"
          ? modelSuggestions.items.length
          : 0;

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
        {usage && turnGaugeTokens(usage) > 0 && (
          <TokenGauge
            usage={usage}
            availableModelEntries={availableModelEntries}
            onClickUsage={
              connected && !waiting ? () => onSend("/usage") : undefined
            }
          />
        )}
      </div>
    </div>
  );
}

/** API input+output tokens for the last agent model request (or last turn slice from done). */
function turnGaugeTokens(u: TurnUsage): number {
  return u.input_tokens + u.output_tokens;
}

const GAUGE_BREAKDOWN_ORDER: {
  key: keyof TurnUsageBreakdownPct;
  label: string;
  className: string;
}[] = [
  { key: "system", label: "system", className: "bg-sky-500/80" },
  { key: "user", label: "user", className: "bg-emerald-500/80" },
  { key: "assistant", label: "assistant", className: "bg-violet-500/80" },
  { key: "tool_calls", label: "tool calls", className: "bg-amber-500/80" },
  { key: "tool_returns", label: "tool outputs", className: "bg-orange-500/80" },
  { key: "other", label: "other", className: "bg-muted-foreground/60" },
];

function breakdownTooltipLines(bp: TurnUsageBreakdownPct): string[] {
  const lines: string[] = [];
  for (const { key, label } of GAUGE_BREAKDOWN_ORDER) {
    const v = bp[key];
    if (key === "other" && v <= 0) continue;
    lines.push(`${label}: ${v.toFixed(1)}%`);
  }
  return lines;
}

const DEFAULT_CONTEXT_CAP = 200_000;

/** Match API ``usage.model`` to a descriptor (canonical id or provider-short name). */
function findModelEntryForGauge(
  modelId: string | null | undefined,
  entries: AvailableModelInfo[],
): AvailableModelInfo | undefined {
  if (!modelId) return undefined;
  const exact = entries.find((e) => e.id === modelId);
  if (exact) return exact;
  const byName = entries.find((e) => e.name === modelId);
  if (byName) return byName;
  return entries.find((e) => e.id.endsWith(`:${modelId}`));
}

function contextTokenCap(
  usage: TurnUsage,
  entries: AvailableModelInfo[],
): number {
  if (
    typeof usage.context_cap_tokens === "number" &&
    usage.context_cap_tokens > 0
  ) {
    return usage.context_cap_tokens;
  }
  const row = findModelEntryForGauge(usage.model, entries);
  if (row?.max_input_tokens != null) return row.max_input_tokens;
  return DEFAULT_CONTEXT_CAP;
}

/** Compact context-window gauge rendered below the input box. */
function TokenGauge({
  usage,
  availableModelEntries,
  onClickUsage,
}: {
  usage: TurnUsage;
  availableModelEntries: AvailableModelInfo[];
  onClickUsage?: () => void;
}) {
  const ctx = turnGaugeTokens(usage);
  const cap = contextTokenCap(usage, availableModelEntries);
  const fillPct = Math.min((ctx / cap) * 100, 100);
  const bp = usage.breakdown_pct;

  const stress = fillPct > 75 ? "high" : fillPct > 50 ? "mid" : "low";
  const trackRing =
    stress === "high"
      ? "ring-1 ring-destructive/35"
      : stress === "mid"
        ? "ring-1 ring-warning/30"
        : "";

  const matched = findModelEntryForGauge(usage.model, availableModelEntries);
  const limitFromConfig = matched?.max_input_tokens != null;
  const limitNote = limitFromConfig
    ? `Context limit: ${formatTokens(cap)} tokens.`
    : `Assuming a ${formatTokens(cap)} context limit.`;

  const tooltipLines = [
    `${formatTokens(ctx)} API tokens (last agent request)`,
    limitNote,
    "Click to send /usage to the agent for more details.",
  ];
  if (bp) {
    tooltipLines.push("", ...breakdownTooltipLines(bp));
  }

  const tooltip = tooltipLines.join("\n");

  return (
    <div className="mt-1.5 flex items-center gap-2 px-1">
      <div
        title={tooltip}
        className="flex min-h-6 flex-1 cursor-default items-center py-2 -my-2"
      >
        <div
          className={cn(
            "relative h-1 w-full rounded-full bg-muted overflow-hidden",
            trackRing,
          )}
        >
          <div
            className="absolute left-0 top-0 h-full flex overflow-hidden rounded-l-full transition-[width]"
            style={{ width: `${fillPct}%` }}
          >
            {bp ? (
              GAUGE_BREAKDOWN_ORDER.map(({ key, className }) => {
                const w = bp[key];
                if (w <= 0) return null;
                return (
                  <div
                    key={key}
                    className={cn("h-full min-w-px shrink-0", className)}
                    style={{ width: `${w}%` }}
                  />
                );
              })
            ) : (
              <div
                className={cn(
                  "h-full w-full rounded-l-full transition-colors",
                  stress === "high"
                    ? "bg-destructive/70"
                    : stress === "mid"
                      ? "bg-warning/70"
                      : "bg-muted-foreground/30",
                )}
              />
            )}
          </div>
        </div>
      </div>
      <button
        type="button"
        onClick={onClickUsage}
        disabled={!onClickUsage}
        title={tooltip}
        className={cn(
          "shrink-0 text-[10px] tabular-nums text-muted-foreground",
          onClickUsage &&
            "hover:text-foreground cursor-pointer transition-colors",
          !onClickUsage && "cursor-default",
        )}
      >
        {formatTokens(ctx)} tokens
      </button>
    </div>
  );
}
