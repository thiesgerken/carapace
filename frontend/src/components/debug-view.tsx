"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { ArrowLeft, Braces, Loader2 } from "lucide-react";
import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";
import { useWebSocket, useWebSocketTicket } from "@/hooks/use-websocket";
import { fetchLlmContext, wsUrl } from "@/lib/api";
import {
  DEBUG_ROLES,
  type DebugRole,
  type LlmContext,
  type LlmContextStatus,
  type LlmMessage,
  type LlmPart,
  type ServerMessage,
} from "@/lib/types";
import { cn } from "@/lib/utils";

export const debugViewHref = (sessionId: string): string => `/?session=${encodeURIComponent(sessionId)}&view=debug`;

const pillClassName = (selected: boolean): string => cn(
  "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm transition-colors",
  selected
    ? "border-[#236b86]/60 bg-[#236b86]/10 text-foreground dark:border-sky-400/50 dark:bg-sky-400/10"
    : "border-border text-muted-foreground hover:bg-muted hover:text-foreground",
);

const STATUS_CLASS: Record<LlmContextStatus, string> = {
  running: "border-sky-500/40 bg-sky-500/10 text-sky-800 dark:text-sky-300",
  completed: "border-emerald-500/40 bg-emerald-500/10 text-emerald-800 dark:text-emerald-300",
  failed: "border-destructive/40 bg-destructive/10 text-destructive",
  interrupted: "border-amber-500/40 bg-amber-500/10 text-amber-800 dark:text-amber-300",
};

type Notification = { requestId: string; status: LlmContextStatus };
type Outcome = { key: string; context: LlmContext | null } | { key: string; error: string };

/** The role's latest context, refetched whenever *revision* (the role's latest notification) changes. */
function useLlmContext(server: string, token: string, sessionId: string, role: DebugRole, revision: string) {
  const key = `${role}:${revision}`;
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchLlmContext(server, token, sessionId, role)
      .then((context) => {
        if (!cancelled) setOutcome({ key, context });
      })
      .catch((loadError: unknown) => {
        if (!cancelled) setOutcome({ key, error: loadError instanceof Error ? loadError.message : String(loadError) });
      });
    return () => {
      cancelled = true;
    };
  }, [server, token, sessionId, role, key]);

  return outcome;
}

/** The latest LLM context of every agent role in a session, updated live over the session WebSocket. */
export function DebugView({ server, token, sessionId }: { server: string; token: string; sessionId: string }) {
  const t = useTranslations("debugView");
  const [role, setRole] = useState<DebugRole>("agent");
  const [notifications, setNotifications] = useState<Partial<Record<DebugRole, Notification>>>({});

  const onMessage = useCallback((msg: ServerMessage) => {
    if (msg.type !== "llm_context") return;
    setNotifications((current) => ({ ...current, [msg.role]: { requestId: msg.request_id, status: msg.status } }));
  }, []);
  const ticket = useWebSocketTicket(server, token);
  useWebSocket(ticket ? wsUrl(server, sessionId, token, undefined, ticket) : null, onMessage);

  const latest = notifications[role];
  const outcome = useLlmContext(server, token, sessionId, role, latest ? `${latest.requestId}:${latest.status}` : "");
  // The role's context from an older notification keeps showing while the next one loads.
  const current = outcome?.key.startsWith(`${role}:`) ? outcome : null;
  const shown = current && "context" in current ? current.context : undefined;

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-4">
        <div className="flex flex-col gap-1">
          <Link href={`/?session=${encodeURIComponent(sessionId)}`} className="inline-flex w-fit items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
            <ArrowLeft className="h-4 w-4" />
            {t("back")}
          </Link>
          <h1 className="text-lg font-semibold">{t("title")}</h1>
          <p className="text-sm text-muted-foreground">{t("hint")}</p>
        </div>

        <div role="radiogroup" aria-label={t("role")} className="flex flex-wrap gap-1.5">
          {DEBUG_ROLES.map((value) => (
            <button key={value} type="button" role="radio" aria-checked={value === role} onClick={() => setRole(value)} className={pillClassName(value === role)}>
              {t(`roles.${value}`)}
              {notifications[value]?.status === "running" ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
            </button>
          ))}
        </div>

        {current && "error" in current ? (
          <p className="text-sm text-destructive">{t("loadError", { error: current.error })}</p>
        ) : shown === undefined ? (
          <Loader2 className="mx-auto mt-8 h-5 w-5 animate-spin text-muted-foreground" />
        ) : shown === null ? (
          <p className="text-sm text-muted-foreground">{t("empty")}</p>
        ) : (
          <LlmContextView context={shown} />
        )}
      </div>
    </div>
  );
}

export function LlmContextView({ context }: { context: LlmContext }) {
  const t = useTranslations("debugView");
  const format = useFormatter();
  const inputTokens = context.response?.usage?.input_tokens;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-start gap-x-8 gap-y-3 rounded-2xl border border-border bg-background/88 p-4 shadow-sm">
        <Stat label={t("status")} value={<StatusBadge status={context.status} />} />
        <Stat label={t("inputTokens")} value={<span className="tabular-nums">{inputTokens === undefined ? "–" : format.number(inputTokens)}</span>} />
        <Stat label={t("model")} value={<span className="font-mono">{context.model_name ?? "–"}</span>} />
        <Stat label={t("started")} value={format.dateTime(new Date(context.started_at), { dateStyle: "medium", timeStyle: "medium" })} />
        {context.compaction_target ? (
          <Stat label={t("compacted")} value={t(`compactionTargets.${context.compaction_target}`)} />
        ) : null}
      </div>

      {context.error ? (
        <pre className="whitespace-pre-wrap break-words rounded-xl border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">{context.error}</pre>
      ) : null}

      <Collapsible title={t("instructions")} open>
        {context.instructions.map((part, index) => (
          <Card key={index} label={part.name ?? t("instructions")} badge={part.dynamic ? t("dynamic") : undefined}>
            <Text>{part.content}</Text>
          </Card>
        ))}
      </Collapsible>

      <Collapsible title={t("tools", { count: context.tool_definitions.length })}>
        {context.tool_definitions.map((tool) => (
          <Card key={tool.name} label={tool.name}>
            {tool.description ? <Text>{tool.description}</Text> : null}
            <Json value={tool.parameters_json_schema} />
          </Card>
        ))}
      </Collapsible>

      <Collapsible title={t("messages", { count: context.messages.length })} open>
        {context.messages.map((message, index) => (
          <MessageCard key={index} message={message} label={t(message.kind === "request" ? "request" : "response")} />
        ))}
      </Collapsible>

      {context.response ? (
        <MessageCard message={context.response} label={t("response")} highlight />
      ) : context.status === "running" ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("waiting")}
        </p>
      ) : null}
    </div>
  );
}

function MessageCard({ message, label, highlight = false }: { message: LlmMessage; label: string; highlight?: boolean }) {
  const t = useTranslations("debugView");
  const [raw, setRaw] = useState(false);

  return (
    <section className={cn("rounded-xl border bg-background p-3", highlight ? "border-[#236b86]/50 dark:border-sky-400/40" : "border-border")}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">{label}</span>
        <button type="button" aria-pressed={raw} onClick={() => setRaw(!raw)} className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground">
          <Braces className="h-3.5 w-3.5" />
          {raw ? t("showCards") : t("showRaw")}
        </button>
      </div>
      {raw ? (
        <Json value={message} />
      ) : (
        <div className="flex flex-col gap-2">
          {message.parts.map((part, index) => <PartCard key={index} part={part} />)}
        </div>
      )}
    </section>
  );
}

function PartCard({ part }: { part: LlmPart }) {
  const t = useTranslations("debugView.parts");
  switch (part.part_kind) {
    case "system-prompt":
      return <Card label={t("systemPrompt")}><Content value={part.content} /></Card>;
    case "user-prompt":
      return <Card label={t("userPrompt")}><Content value={part.content} /></Card>;
    case "text":
      return <Card label={t("text")}><Content value={part.content} /></Card>;
    case "thinking":
      return <Card label={t("thinking")} muted><Content value={part.content} /></Card>;
    case "tool-call":
      return <Card label={`${t("toolCall")} · ${part.tool_name}`} badge={part.tool_call_id}><Json value={parseArgs(part.args)} /></Card>;
    case "tool-return":
      return <Card label={`${t("toolReturn")} · ${part.tool_name}`} badge={part.tool_call_id}><Content value={part.content} /></Card>;
    case "retry-prompt":
      return <Card label={t("retryPrompt")} badge={part.tool_call_id}><Content value={part.content} /></Card>;
    default:
      // Provider-specific parts (native tools, files, compaction) render as what they are.
      return <Card label={part.part_kind}><Json value={part} /></Card>;
  }
}

/** pydantic-ai keeps tool call args either as a dict or as the model's raw JSON string. */
function parseArgs(args: unknown): unknown {
  if (typeof args !== "string") return args;
  try {
    return JSON.parse(args);
  } catch {
    return args;
  }
}

function Content({ value }: { value: unknown }) {
  return typeof value === "string" ? <Text>{value}</Text> : <Json value={value} />;
}

function Text({ children }: { children: string }) {
  return <pre className="whitespace-pre-wrap break-words font-sans text-sm">{children}</pre>;
}

function Json({ value }: { value: unknown }) {
  return <pre className="overflow-x-auto rounded-lg bg-muted/50 p-2 font-mono text-xs">{typeof value === "string" ? value : JSON.stringify(value, null, 2)}</pre>;
}

function Card({ label, badge, muted = false, children }: { label: string; badge?: string; muted?: boolean; children: ReactNode }) {
  return (
    <div className={cn("min-w-0 rounded-lg border border-border/70 p-2.5", muted && "bg-muted/30 text-muted-foreground")}>
      <div className="mb-1.5 flex min-w-0 items-center justify-between gap-2 text-xs font-medium">
        <span className="truncate">{label}</span>
        {badge ? <span className="truncate font-mono text-[11px] text-muted-foreground">{badge}</span> : null}
      </div>
      {children}
    </div>
  );
}

function Collapsible({ title, open = false, children }: { title: string; open?: boolean; children: ReactNode }) {
  return (
    <details open={open} className="group rounded-2xl border border-border bg-muted/20 p-3">
      <summary className="cursor-pointer text-sm font-medium">{title}</summary>
      <div className="mt-3 flex flex-col gap-2">{children}</div>
    </details>
  );
}

function StatusBadge({ status }: { status: LlmContextStatus }) {
  const t = useTranslations("debugView.statuses");
  return <span className={cn("inline-flex rounded-full border px-2 py-0.5 text-xs font-medium", STATUS_CLASS[status])}>{t(status)}</span>;
}

function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <span className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">{label}</span>
      <span className="text-sm">{value}</span>
    </div>
  );
}
