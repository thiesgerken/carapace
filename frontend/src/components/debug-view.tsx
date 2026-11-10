"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Braces, Loader2 } from "lucide-react";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import { useFormatCost } from "@/components/memory-ui";
import { MarkdownContent } from "@/components/markdown-content";
import { pillClassName } from "@/components/prompt-preview-view";
import { SessionHeader } from "@/components/session-header";
import { useWebSocket, useWebSocketTicket } from "@/hooks/use-websocket";
import { fetchLlmContext, fetchLlmRequests, wsUrl } from "@/lib/api";
import { formatUsd } from "@/lib/memory";
import { fencedCodeBlock } from "@/lib/sandbox-read";
import {
  DEBUG_ROLES,
  type DebugRole,
  type LlmContext,
  type LlmContextStatus,
  type LlmMessage,
  type LlmRequestCost,
  type LlmRequestUsage,
  type LlmPart,
  type LlmRequestRecord,
  type ServerMessage,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS_CLASS: Record<LlmContextStatus, string> = {
  running: "border-sky-500/40 bg-sky-500/10 text-sky-800 dark:text-sky-300",
  completed: "border-emerald-500/40 bg-emerald-500/10 text-emerald-800 dark:text-emerald-300",
  failed: "border-destructive/40 bg-destructive/10 text-destructive",
  interrupted: "border-amber-500/40 bg-amber-500/10 text-amber-800 dark:text-amber-300",
};

type Notification = { requestId: string; status: LlmContextStatus };
type Outcome<T> = { key: string; value: T } | { key: string; error: string };
type RoleFetch<T> = (server: string, token: string, sessionId: string, role: DebugRole) => Promise<T>;

/** What *fetchRole* returns for *role*, refetched whenever *revision* (the role's latest notification) changes. */
function useRoleFetch<T>(fetchRole: RoleFetch<T>, server: string, token: string, sessionId: string, role: DebugRole, revision: string) {
  const key = `${role}:${revision}`;
  const [outcome, setOutcome] = useState<Outcome<T> | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchRole(server, token, sessionId, role)
      .then((value) => {
        if (!cancelled) setOutcome({ key, value });
      })
      .catch((loadError: unknown) => {
        if (!cancelled) setOutcome({ key, error: loadError instanceof Error ? loadError.message : String(loadError) });
      });
    return () => {
      cancelled = true;
    };
  }, [fetchRole, server, token, sessionId, role, key]);

  // A result for another role keeps showing while this one loads, so it is dropped here.
  return outcome?.key.startsWith(`${role}:`) ? outcome : null;
}

/** The latest LLM context of every agent role in a session, updated live over the session WebSocket. */
export function DebugView({ server, token, sessionId, title }: { server: string; token: string; sessionId: string; title: string | null | undefined }) {
  const t = useTranslations("debugView");
  const [role, setRole] = useState<DebugRole>("agent");
  const [notifications, setNotifications] = useState<Partial<Record<DebugRole, Notification>>>({});
  const [activityEnds, setActivityEnds] = useState(0);

  const onMessage = useCallback((msg: ServerMessage) => {
    if (msg.type === "llm_activity" && !msg.activity) setActivityEnds((count) => count + 1);
    if (msg.type !== "llm_context") return;
    setNotifications((current) => ({ ...current, [msg.role]: { requestId: msg.request_id, status: msg.status } }));
  }, []);
  const ticket = useWebSocketTicket(server, token);
  const { status } = useWebSocket(ticket ? wsUrl(server, sessionId, token, undefined, ticket, true) : null, onMessage);

  const latest = notifications[role];
  // Notifications sent while the socket was down are lost, so every (re)connect refetches too.
  const revision = `${status === "connected"}:${latest ? `${latest.requestId}:${latest.status}` : ""}`;
  // The role's context and timeline from an older notification keep showing while the next ones load.
  const current = useRoleFetch(fetchLlmContext, server, token, sessionId, role, revision);
  const shown = current && "value" in current ? current.value : undefined;
  // A stopped turn saves its interrupted record after the context's notification went out; the activity ends after that.
  const timeline = useRoleFetch(fetchLlmRequests, server, token, sessionId, role, `${revision}:${activityEnds}`);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <SessionHeader sessionId={sessionId} title={title} view="debug" />
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-4">
        <p className="text-sm text-muted-foreground">{t("hint")}</p>

        <div role="radiogroup" aria-label={t("role")} className="flex flex-wrap gap-1.5">
          {DEBUG_ROLES.map((value) => (
            <button key={value} type="button" role="radio" aria-checked={value === role} onClick={() => setRole(value)} className={cn(pillClassName(value === role), "inline-flex items-center gap-1.5")}>
              {t(`roles.${value}`)}
              {notifications[value]?.status === "running" ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
            </button>
          ))}
        </div>

        {timeline && "error" in timeline ? (
          <p className="text-sm text-destructive">{t("timeline.loadError", { error: timeline.error })}</p>
        ) : timeline?.value.length ? (
          <RequestTimeline records={timeline.value} contextRequestId={shown?.request_id} />
        ) : null}

        {current && "error" in current ? (
          <p className="text-sm text-destructive">{t("loadError", { error: current.error })}</p>
        ) : shown === undefined ? (
          <Loader2 className="mx-auto mt-8 h-5 w-5 animate-spin text-muted-foreground" />
        ) : shown === null ? (
          <p className="text-sm text-muted-foreground">{t("empty")}</p>
        ) : (
          <div id={CONTEXT_ANCHOR} className="scroll-mt-4">
            <LlmContextView context={shown} />
          </div>
        )}
      </div>
      </div>
    </div>
  );
}

export function LlmContextView({ context }: { context: LlmContext }) {
  const t = useTranslations("debugView");
  const format = useFormatter();

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-start gap-x-8 gap-y-3 rounded-2xl border border-border bg-background/88 p-4 shadow-sm">
        <Stat label={t("status")} value={<StatusBadge status={context.status} />} />
        <Stat label={t("model")} value={<span className="font-mono">{context.model_name}</span>} />
        <Stat label={t("started")} value={format.dateTime(new Date(context.started_at), { dateStyle: "medium", timeStyle: "medium" })} />
        {context.compaction_target ? (
          <Stat label={t("compacted")} value={t(`compactionTargets.${context.compaction_target}`)} />
        ) : null}
        {context.response?.usage ? <UsageStats usage={context.response.usage} cost={context.cost} /> : null}
      </div>

      {context.error ? (
        <pre className="whitespace-pre-wrap break-words rounded-xl border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">{context.error}</pre>
      ) : null}

      <Collapsible title={t("instructions")} open>
        {context.instructions.map((part, index) => (
          <Card key={index} label={part.name ?? t(part.dynamic ? "dynamic" : "static")}>
            <MarkdownContent content={part.content} />
          </Card>
        ))}
      </Collapsible>

      <Collapsible title={t("tools", { count: context.tool_definitions.length })}>
        {context.tool_definitions.map((tool) => (
          <Card key={tool.name} label={tool.name}>
            {tool.description ? <MarkdownContent content={tool.description} /> : null}
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

const CONTEXT_ANCHOR = "llm-context";

type TimelineColumn = { key: string; numeric?: boolean; cell: (record: LlmRequestRecord) => ReactNode };

/** One row per recorded request of the role, newest first, so requests compare side by side without their contexts. */
function RequestTimeline({ records, contextRequestId }: { records: LlmRequestRecord[]; contextRequestId: string | undefined }) {
  const t = useTranslations("debugView.timeline");
  const format = useFormatter();
  const locale = useLocale();
  // Null counts and costs are unknown: the record predates them, or the model has no pricing.
  const count = (value: number | null) => (value === null ? "–" : format.number(value));
  const usd = (value: string | null | undefined) => (value == null ? "–" : formatUsd(value, locale));
  const columns: TimelineColumn[] = [
    { key: "time", cell: (r) => <Time record={r} linked={r.request_id !== null && r.request_id === contextRequestId} /> },
    { key: "status", cell: (r) => <StatusBadge status={r.outcome} /> },
    { key: "input", numeric: true, cell: (r) => count(r.input_tokens) },
    { key: "cacheRead", numeric: true, cell: (r) => count(r.cache_read_tokens) },
    { key: "cacheWrite", numeric: true, cell: (r) => count(r.cache_write_tokens) },
    { key: "output", numeric: true, cell: (r) => count(r.output_tokens) },
    { key: "reasoning", numeric: true, cell: (r) => count(r.reasoning_tokens) },
    {
      key: "cacheHitRate",
      numeric: true,
      cell: (r) => (r.cache_read_tokens === null || r.input_tokens === 0 ? "–" : format.number(r.cache_read_tokens / r.input_tokens, { style: "percent", maximumFractionDigits: 0 })),
    },
    { key: "cost", numeric: true, cell: (r) => usd(r.cost?.cost_usd) },
    { key: "equivalentCost", numeric: true, cell: (r) => usd(r.cost?.equivalent_cost_usd) },
    {
      key: "duration",
      numeric: true,
      cell: (r) => (r.started_at && r.completed_at ? t("seconds", { seconds: format.number((Date.parse(r.completed_at) - Date.parse(r.started_at)) / 1000, { maximumFractionDigits: 1 }) }) : "–"),
    },
    { key: "model", cell: (r) => <span className="font-mono">{r.model_name ?? "–"}</span> },
  ];

  return (
    <Collapsible title={t("title", { count: records.length })} open>
      <div className="overflow-x-auto">
        <table className="w-full whitespace-nowrap text-xs">
          <thead>
            <tr className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              {columns.map((column) => (
                <th key={column.key} scope="col" className={cn("px-2 py-1.5 font-medium", column.numeric ? "text-right" : "text-left")}>{t(`columns.${column.key}`)}</th>
              ))}
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {[...records].reverse().map((record, index) => (
              <tr key={record.request_id ?? index} className={cn("border-t border-border/60", record.request_id !== null && record.request_id === contextRequestId && "bg-sky-500/10")}>
                {columns.map((column) => (
                  <td key={column.key} className={cn("px-2 py-1.5", column.numeric && "text-right")}>{column.cell(record)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Collapsible>
  );
}

/** Day and time are enough to tell requests apart; the full timestamp is in the tooltip. The shown context's row links to it. */
function Time({ record, linked }: { record: LlmRequestRecord; linked: boolean }) {
  const t = useTranslations("debugView.timeline");
  const format = useFormatter();
  const date = new Date(record.ts);
  const short = format.dateTime(date, { month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" });
  const full = format.dateTime(date, { dateStyle: "medium", timeStyle: "medium" });
  return linked ? (
    <a href={`#${CONTEXT_ANCHOR}`} title={`${full} · ${t("showContext")}`} className="underline underline-offset-2">{short}</a>
  ) : (
    <span title={full}>{short}</span>
  );
}

const AUDIO_TOKENS = ["input_audio_tokens", "output_audio_tokens", "cache_audio_read_tokens"] as const;

/** The response's usage as the provider reported it, and what it cost. */
function UsageStats({ usage, cost }: { usage: LlmRequestUsage; cost: LlmRequestCost | null }) {
  const t = useTranslations("debugView.usage");
  const format = useFormatter();
  const locale = useLocale();
  const formatCost = useFormatCost();
  const tokens = (value: number | undefined) => <span className="tabular-nums">{format.number(value ?? 0)}</span>;

  return (
    <div className="flex basis-full flex-wrap gap-x-8 gap-y-3 border-t border-border/60 pt-3">
      <Stat label={t("input")} value={tokens(usage.input_tokens)} />
      <Stat label={t("output")} value={tokens(usage.output_tokens)} />
      <Stat label={t("cacheRead")} value={tokens(usage.cache_read_tokens)} />
      <Stat label={t("cacheWrite")} value={tokens(usage.cache_write_tokens)} />
      {AUDIO_TOKENS.filter((key) => usage[key]).map((key) => (
        <Stat key={key} label={t(key)} value={tokens(usage[key])} />
      ))}
      {Object.entries(usage.details ?? {}).map(([key, value]) => (
        <Stat key={key} label={key} value={tokens(value)} />
      ))}
      {cost ? <Stat label={t("cost")} value={formatCost(cost) ?? t("unpriced")} /> : null}
      {cost?.provider_cost_usd ? <Stat label={t("providerCost")} value={formatUsd(cost.provider_cost_usd, locale)} /> : null}
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
          {raw ? t("showFormatted") : t("showRaw")}
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
      return <Card label={t("systemPrompt")}><Content value={part.content} markdown /></Card>;
    case "user-prompt":
      return <Card label={t("userPrompt")}><Content value={part.content} markdown /></Card>;
    case "text":
      return <Card label={t("text")}><Content value={part.content} markdown /></Card>;
    case "thinking":
      return <Card label={t("thinking")} muted><Content value={part.content} markdown /></Card>;
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

/** Prose to and from the model renders as Markdown; tool output stays verbatim, Markdown would mangle it. */
function Content({ value, markdown = false }: { value: unknown; markdown?: boolean }) {
  if (typeof value !== "string") return <Json value={value} />;
  return markdown ? <MarkdownContent content={value} /> : <Verbatim>{value}</Verbatim>;
}

function Verbatim({ children }: { children: string }) {
  return <pre className="whitespace-pre-wrap break-words rounded-lg bg-muted/50 p-2 font-mono text-xs">{children}</pre>;
}

/** A string is tool call args the model sent as invalid JSON: shown as sent, not highlighted as JSON. */
function Json({ value }: { value: unknown }) {
  if (typeof value === "string") return <Verbatim>{value}</Verbatim>;
  return <MarkdownContent content={fencedCodeBlock("json", JSON.stringify(value, null, 2))} />;
}

function Card({ label, badge, muted = false, children }: { label: string; badge?: string; muted?: boolean; children: ReactNode }) {
  return (
    <div className={cn("min-w-0 rounded-lg border border-border/70 p-2.5 text-sm", muted && "bg-muted/30 text-muted-foreground")}>
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
