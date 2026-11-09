"use client";

import { useTranslations } from "next-intl";
import { useState, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  decodeAvailableModel,
  decodeSlashCommand,
  type AvailableModelInfo,
  type SlashCommand,
} from "@/lib/api";
import { isRecord, readString } from "@/lib/decoding";
import type { BudgetGauge } from "@/lib/types";

interface HelpData {
  commands: SlashCommand[];
}

interface RuleRow {
  id: string;
  trigger: string;
  mode: string;
  status: string;
}

interface ModelSelection {
  current: string;
  default: string;
}

interface ModelData {
  current?: string;
  default?: string;
  message?: string;
  error?: string;
  models?: Record<string, ModelSelection>;
  available?: AvailableModelInfo[];
}

interface MessageData {
  message?: string;
  error?: string;
}

interface CommandResultViewProps {
  command: string;
  data: unknown;
  /** True when the result just arrived live (vs. replayed from history). */
  defaultExpanded?: boolean;
}

function ruleStatusLabel(
  status: string,
  t: (key: string, values?: Record<string, string | number>) => string,
): string {
  switch (status) {
    case "disabled":
      return t("rules.status.disabled");
    case "always-on":
      return t("rules.status.alwaysOn");
    case "activated":
      return t("rules.status.activated");
    default:
      return status;
  }
}

export function CommandResultView({
  command,
  data,
  defaultExpanded,
}: CommandResultViewProps) {
  const t = useTranslations("commandResult");
  const helpData = decodeHelpData(data);
  if (command === "help" && helpData) {
    return (
      <div className="my-2 text-sm">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="pb-1 pr-4 font-medium">{t("help.command")}</th>
              <th className="pb-1 font-medium">{t("help.description")}</th>
            </tr>
          </thead>
          <tbody>
            {helpData.commands.map((c) => (
              <tr key={c.command} className="border-b border-border/50">
                <td className="py-1 pr-4 font-mono text-xs">{c.command}</td>
                <td className="py-1 text-muted-foreground">{c.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  const rulesData = decodeRulesData(data);
  if (command === "rules" && rulesData) {
    return (
      <div className="my-2 text-sm">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="pb-1 pr-3 font-medium">{t("rules.id")}</th>
              <th className="pb-1 pr-3 font-medium">{t("rules.trigger")}</th>
              <th className="pb-1 pr-3 font-medium">{t("rules.mode")}</th>
              <th className="pb-1 font-medium">{t("rules.status.label")}</th>
            </tr>
          </thead>
          <tbody>
            {rulesData.map((r) => (
              <tr key={r.id} className="border-b border-border/50">
                <td className="py-1 pr-3 font-mono text-xs">{r.id}</td>
                <td className="py-1 pr-3 text-xs">{r.trigger}</td>
                <td className="py-1 pr-3 text-xs">{r.mode}</td>
                <td className="py-1 text-xs">
                  <span
                    className={
                      r.status === "disabled"
                        ? "text-destructive"
                        : r.status === "always-on"
                          ? "text-green-600 dark:text-green-400"
                          : r.status === "activated"
                            ? "text-warning"
                            : "text-muted-foreground"
                    }
                  >
                    {ruleStatusLabel(r.status, t)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  const modelData = decodeModelData(data);
  if (command === "models" && modelData?.available) {
    const available = modelData.available;
    return (
      <div className="my-2 text-sm">
        {available.length === 0 ? (
          <p className="text-muted-foreground">{t("models.noneAvailable")}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground">
                  <th className="pb-1 pr-4 font-medium">{t("models.model")}</th>
                  <th className="pb-1 pr-4 font-medium">{t("models.provider")}</th>
                  <th className="pb-1 pr-4 font-medium">{t("models.name")}</th>
                  <th className="pb-1 font-medium">{t("models.context")}</th>
                </tr>
              </thead>
              <tbody>
                {available.map((entry) => {
                  const maxTok = entry.max_input_tokens ?? null;
                  return (
                    <tr key={entry.id} className="border-b border-border/50 align-top">
                      <td className="py-1 pr-4 font-mono text-xs text-foreground">{entry.id}</td>
                      <td className="py-1 pr-4 text-xs text-muted-foreground">{entry.provider || "-"}</td>
                      <td className="py-1 pr-4 text-xs">{entry.name || entry.id}</td>
                      <td className="py-1 text-xs text-muted-foreground">
                        {maxTok == null ? "-" : t("models.contextWindowShort", { tokens: maxTok.toLocaleString() })}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    );
  }

  if (
    modelData?.models &&
    command === "model"
  ) {
    const models = modelData.models;
    return (
      <div className="my-2 text-sm">
        {command === "model" && modelData.error ? (
          <p className="mb-2 text-sm text-destructive">{modelData.error}</p>
        ) : null}
        <table className="w-full">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="pb-1 pr-4 font-medium">{t("models.type")}</th>
              <th className="pb-1 pr-4 font-medium">{t("models.model")}</th>
              <th className="pb-1 font-medium">{t("models.default")}</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(models).map(([type, info]) => (
              <tr key={type} className="border-b border-border/50">
                <td className="py-1 pr-4 text-xs font-medium">{type}</td>
                <td className="py-1 pr-4 font-mono text-xs">{info.current}</td>
                <td className="py-1 text-xs text-muted-foreground">
                  {info.current !== info.default ? info.default : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {command === "model" && modelData.message ? (
          <p className="mt-2 text-sm text-muted-foreground">{modelData.message}</p>
        ) : null}
      </div>
    );
  }

  if (
    (command === "model-agent" ||
      command === "model-sentinel" ||
      command === "model-title" ||
      command === "model-compaction") &&
    modelData
  ) {
    if (modelData.error)
      return <p className="my-1 text-sm text-destructive">{modelData.error}</p>;
    if (modelData.message)
      return (
        <p className="my-1 text-sm text-muted-foreground">{modelData.message}</p>
      );
    return (
      <div className="my-1 text-sm">
        <p>
          <span className="text-muted-foreground">{t("models.currentLabel")} </span>
          <span className="font-mono">{modelData.current}</span>
        </p>
        {modelData.default && modelData.default !== modelData.current && (
          <p className="text-xs text-muted-foreground">
            {t("models.defaultLabel", { model: modelData.default })}
          </p>
        )}
      </div>
    );
  }

  if (command === "model" && modelData) {
    if (modelData.error)
      return <p className="my-1 text-sm text-destructive">{modelData.error}</p>;
    if (modelData.message)
      return (
        <p className="my-1 text-sm text-muted-foreground">{modelData.message}</p>
      );
    return (
      <div className="my-1 text-sm">
        <p>
          <span className="text-muted-foreground">{t("models.currentLabel")} </span>
          <span className="font-mono">{modelData.current}</span>
        </p>
        {modelData.default && modelData.default !== modelData.current && (
          <p className="text-xs text-muted-foreground">
            {t("models.defaultLabel", { model: modelData.default })}
          </p>
        )}
      </div>
    );
  }

  const messageData = decodeMessageData(data);
  if ((command === "disable" || command === "enable") && messageData) {
    if (messageData.error)
      return <p className="my-1 text-sm text-destructive">{messageData.error}</p>;
    return <p className="my-1 text-sm text-muted-foreground">{messageData.message}</p>;
  }

  if (command === "usage" && isUsageData(data)) {
    return <UsageView data={data} defaultExpanded={defaultExpanded ?? false} />;
  }

  if (command === "budget" && isBudgetData(data)) {
    return <BudgetView data={data} />;
  }

  if (command === "compact") {
    return <CompactView data={data} />;
  }

  if (command === "uncompact" && isRecord(data)) {
    // Payload carries restored/token counts alongside a human-readable `message`; the strict
    // plain-message decoder rejects the extra keys, so render the message directly here.
    const error = typeof data.error === "string" ? data.error : undefined;
    const message = typeof data.message === "string" ? data.message : "";
    if (error || message) {
      return (
        <p className={`my-1 text-sm whitespace-pre-wrap ${error ? "text-destructive" : "text-muted-foreground"}`}>
          {error ?? message}
        </p>
      );
    }
  }

  const plainMessage = decodePlainMessagePayload(data);
  if (plainMessage) {
    if (plainMessage.error) {
      return <p className="my-1 text-sm text-destructive">{plainMessage.error}</p>;
    }
    const failed = /\bfailed\b/i.test(plainMessage.message);
    return (
      <p
        className={`my-1 text-sm whitespace-pre-wrap ${failed ? "text-destructive" : "text-muted-foreground"}`}
      >
        {plainMessage.message}
      </p>
    );
  }

  return (
    <pre className="my-2 rounded-md bg-muted p-2 text-xs font-mono overflow-x-auto">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

function CompactView({ data }: { data: unknown }) {
  const t = useTranslations("commandResult.compact");
  const d = isRecord(data) ? data : {};
  const error = typeof d.error === "string" ? d.error : undefined;
  if (error) {
    return <p className="my-1 text-sm text-destructive">{error}</p>;
  }
  const num = (k: string) => (typeof d[k] === "number" ? (d[k] as number) : 0);
  const before = num("before_tokens");
  const after = num("after_tokens");
  const folded = num("turns_folded");
  const tools = num("tool_returns_compacted");
  const thinking = num("thinking_dropped");
  const nothing = folded === 0 && tools === 0 && thinking === 0;
  const lines: string[] = [];
  if (folded) lines.push(t("folded", { count: folded }));
  if (tools) lines.push(t("tools", { count: tools }));
  if (thinking) lines.push(t("thinking", { count: thinking }));
  return (
    <div className="my-2 rounded-lg border border-border/60 bg-muted/30 p-3 text-sm">
      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {t("title")}
      </div>
      {nothing ? (
        <p className="mt-1 text-muted-foreground">{t("nothing")}</p>
      ) : (
        <>
          <p className="mt-1 font-medium">
            {t("saved", {
              saved: Math.max(0, before - after).toLocaleString(),
              before: before.toLocaleString(),
              after: after.toLocaleString(),
            })}
          </p>
          {lines.length > 0 && (
            <ul className="mt-1 list-inside list-disc text-muted-foreground">
              {lines.map((line, i) => (
                <li key={i}>{line}</li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

function decodeHelpData(d: unknown): HelpData | null {
  if (!isRecord(d)) return null;
  const commands = d.commands;
  if (!Array.isArray(commands)) return null;

  const decoded = commands
    .map((entry) => decodeSlashCommand(entry))
    .filter((entry): entry is SlashCommand => entry !== null);

  return { commands: decoded };
}

function decodeRulesData(d: unknown): RuleRow[] | null {
  if (!Array.isArray(d)) return null;

  return d
    .map((entry) => {
      if (!isRecord(entry)) return null;
      const id = readString(entry, "id");
      const trigger = readString(entry, "trigger");
      const mode = readString(entry, "mode");
      const status = readString(entry, "status");
      if (!id || !trigger || !mode || !status) return null;
      return { id, trigger, mode, status };
    })
    .filter((entry): entry is RuleRow => entry !== null);
}

function decodeModelSelections(
  raw: unknown,
): Record<string, ModelSelection> | undefined {
  if (!isRecord(raw)) return undefined;

  const entries = Object.entries(raw)
    .map(([key, value]) => {
      if (!isRecord(value)) return null;
      const current = readString(value, "current");
      const fallback = readString(value, "default");
      if (current === undefined || fallback === undefined) return null;
      return [key, { current, default: fallback }] as const;
    })
    .filter(
      (
        entry,
      ): entry is readonly [string, ModelSelection] => entry !== null,
    );

  return Object.fromEntries(entries);
}

function decodeModelData(d: unknown): ModelData | null {
  if (!isRecord(d)) return null;

  const available = Array.isArray(d.available)
    ? d.available
      .map((entry) => decodeAvailableModel(entry))
      .filter((entry): entry is AvailableModelInfo => entry !== null)
    : undefined;

  return {
    current: readString(d, "current"),
    default: readString(d, "default"),
    message: readString(d, "message"),
    error: readString(d, "error"),
    models: decodeModelSelections(d.models),
    available,
  };
}

function decodeMessageData(d: unknown): MessageData | null {
  if (!isRecord(d)) return null;
  const message = readString(d, "message");
  const error = readString(d, "error");
  if (message === undefined && error === undefined) return null;
  return { message, error };
}

/** Object with only message (and optional error) — avoids JSON dump for simple slash results. */
function decodePlainMessagePayload(
  d: unknown,
): { message: string; error?: string } | null {
  if (!isRecord(d)) return null;
  const message = readString(d, "message");
  if (message === undefined) return null;
  const error = readString(d, "error");
  for (const k of Object.keys(d)) {
    if (k === "message") continue;
    if (k === "error" && error !== undefined) continue;
    return null;
  }
  return error === undefined ? { message } : { message, error };
}

interface UsageBucket {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  input_audio_tokens: number;
  output_audio_tokens: number;
  cache_audio_read_tokens: number;
  requests: number;
}

/** % of tiktoken mass over the prompt only (sum 100); unrelated to API billing tokens. */
interface LastLlmBreakdownPct {
  system: number | null;
  user: number | null;
  assistant: number | null;
  tool_calls: number | null;
  tool_returns: number | null;
  other: number | null;
}

interface LastLlmRequestRow {
  source: string;
  input_tokens: number;
  output_tokens: number;
  context_size: number;
  breakdown_pct: LastLlmBreakdownPct;
  /** Config (or default) context window used for ``context_used_pct``. */
  context_cap_tokens?: number;
  /** Share of context cap used by input+output tokens for this request (0–100). */
  context_used_pct?: number;
}

interface UsagePayload {
  models: Record<string, UsageBucket>;
  categories: Record<string, UsageBucket>;
  total_input: number;
  total_output: number;
  total_tool_calls?: number;
  /** One number per model; subscription models show their list price, marked as such. */
  model_costs?: Record<string, { cost: string; subscription: boolean }>;
  category_costs?: Record<string, CostSplit>;
  total_cost?: CostSplit;
  budget_gauges?: BudgetGauge[];
  last_llm_agent?: LastLlmRequestRow | null;
  last_llm_sentinel?: LastLlmRequestRow | null;
}

/** USD amounts as decimal strings: billed per token, and at list price with subscription usage included. */
interface CostSplit {
  actual: string;
  equivalent: string;
}

interface BudgetPayload {
  gauges: BudgetGauge[];
  message?: string;
  error?: string;
  usage_hint?: string;
}

function isUsageData(d: unknown): d is UsagePayload {
  return !!d && typeof d === "object" && "models" in d && "categories" in d;
}

function isBudgetData(d: unknown): d is BudgetPayload {
  return !!d && typeof d === "object" && "gauges" in d;
}

function fmt(n: number): string {
  return n.toLocaleString();
}

function costColor(val: number): string {
  if (val >= 0.25) return "text-red-600 dark:text-red-400";
  if (val >= 0.1) return "text-yellow-600 dark:text-yellow-400";
  if (val > 0) return "text-green-600 dark:text-green-400";
  return ""; // zero cost ("-") stays normal text color
}

function fmtCost(val: string): string {
  const n = parseFloat(val);
  return n ? `$${n.toFixed(4)}` : "-";
}

function fmtPctCell(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${v.toFixed(1)}%`;
}

function lastRequestRowsShowOtherPct(rows: LastLlmRequestRow[]): boolean {
  return rows.some((r) => (r.breakdown_pct?.other ?? 0) > 0);
}

function UsageView({
  data,
  defaultExpanded,
}: {
  data: UsagePayload;
  defaultExpanded: boolean;
}) {
  const t = useTranslations("commandResult");
  const [open, setOpen] = useState(defaultExpanded);
  const budgetGauges = Array.isArray(data.budget_gauges) ? data.budget_gauges : [];
  const totalToolCalls = data.total_tool_calls ?? 0;
  const allBuckets = [
    ...Object.values(data.models),
    ...Object.values(data.categories),
  ];
  const hasCache = allBuckets.some(
    (b) => b.cache_read_tokens || b.cache_write_tokens,
  );
  const modelCosts = data.model_costs ?? {};
  const categoryCosts = data.category_costs ?? {};
  const hasCosts = Object.values(modelCosts).some((cost) => parseFloat(cost.cost) > 0);
  // The equivalent total follows its gauge: shown with a limit or when the session used a subscription.
  const showEquivalentTotal = budgetGauges.some((gauge) => gauge.key === "equivalent_cost");
  const isEmpty =
    Object.keys(data.models).length === 0 &&
    Object.keys(data.categories).length === 0 &&
    budgetGauges.length === 0 &&
    totalToolCalls === 0;
  if (isEmpty) {
    return (
      <p className="my-1 text-sm text-muted-foreground">
        {t("usage.none")}
      </p>
    );
  }

  function modelCostCell(name: string) {
    const cost = modelCosts[name];
    if (!cost) return fmtCost("0");
    return (
      <>
        <span className={costColor(parseFloat(cost.cost))}>{fmtCost(cost.cost)}</span>
        {cost.subscription ? <span className="text-muted-foreground">{t("usage.subscription")}</span> : null}
      </>
    );
  }

  function categoryCostCell(name: string) {
    const cost = categoryCosts[name] ?? { actual: "0", equivalent: "0" };
    return (
      <>
        <span className={costColor(parseFloat(cost.actual))}>{fmtCost(cost.actual)}</span>
        {parseFloat(cost.equivalent) !== parseFloat(cost.actual) ? (
          <span className="text-muted-foreground">
            {" "}
            {t("usage.equivalent", { cost: fmtCost(cost.equivalent) })}
          </span>
        ) : null}
      </>
    );
  }

  function renderTable(
    title: string,
    rows: Record<string, UsageBucket>,
    costCell: (name: string) => ReactNode,
  ) {
    return (
      <div className="my-2 text-sm">
        <p className="mb-1 text-xs font-medium text-muted-foreground">
          {title}
        </p>
        <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="pb-1 pr-3 font-medium">{t("usage.table.source")}</th>
              <th className="pb-1 pr-3 font-medium text-right">{t("usage.table.input")}</th>
              <th className="pb-1 pr-3 font-medium text-right">{t("usage.table.output")}</th>
              {hasCache && (
                <th className="pb-1 pr-3 font-medium text-right">{t("usage.table.cacheRead")}</th>
              )}
              {hasCache && (
                <th className="pb-1 pr-3 font-medium text-right">
                  {t("usage.table.cacheWrite")}
                </th>
              )}
              <th className="pb-1 pr-3 font-medium text-right">{t("usage.table.requests")}</th>
              {hasCosts && (
                <th className="pb-1 font-medium text-right">{t("usage.table.cost")}</th>
              )}
            </tr>
          </thead>
          <tbody>
            {Object.entries(rows).map(([name, u]) => (
              <tr key={name} className="border-b border-border/50">
                <td className="py-1 pr-3 font-mono text-xs">{name}</td>
                <td className="py-1 pr-3 text-xs text-right">
                  {fmt(u.input_tokens)}
                </td>
                <td className="py-1 pr-3 text-xs text-right">
                  {fmt(u.output_tokens)}
                </td>
                {hasCache && (
                  <td className="py-1 pr-3 text-xs text-right">
                    {fmt(u.cache_read_tokens)}
                  </td>
                )}
                {hasCache && (
                  <td className="py-1 pr-3 text-xs text-right">
                    {fmt(u.cache_write_tokens)}
                  </td>
                )}
                <td className="py-1 pr-3 text-xs text-right">{u.requests}</td>
                {hasCosts && (
                  <td className="py-1 text-xs text-right">{costCell(name)}</td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>
    );
  }

  const total = data.total_input + data.total_output;
  const totalCost = data.total_cost ?? { actual: "0", equivalent: "0" };
  const costStr = (
    <>
      {parseFloat(totalCost.actual) ? (
        <span className={costColor(parseFloat(totalCost.actual))}>
          {" "}
          | {fmtCost(totalCost.actual)}
        </span>
      ) : null}
      {showEquivalentTotal ? (
        <span className="text-muted-foreground">
          {" "}
          {t("usage.equivalent", { cost: fmtCost(totalCost.equivalent) })}
        </span>
      ) : null}
    </>
  );

  const lastRequestRows = (
    [data.last_llm_agent, data.last_llm_sentinel] as const
  ).filter(
    (r): r is LastLlmRequestRow =>
      r != null && typeof r.context_size === "number" && r.context_size > 0,
  );
  const showOtherPctCol = lastRequestRowsShowOtherPct(lastRequestRows);

  return (
    <div className="my-1 w-full min-w-0">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "flex w-full min-w-0 items-center gap-1.5 rounded-md px-2 py-1 text-xs text-left",
          "text-muted-foreground hover:bg-accent transition-colors",
          open && "bg-accent",
        )}
      >
        <ChevronRight
          className={cn(
            "h-3 w-3 shrink-0 transition-transform",
            open && "rotate-90",
          )}
        />
        <span className="min-w-0 flex-1 truncate">
          {t("usage.total", {
            total: fmt(total),
            input: fmt(data.total_input),
            output: fmt(data.total_output),
          })}
          {costStr}
          {" · "}
          {t("usage.toolCalls", { count: fmt(totalToolCalls) })}
        </span>
      </button>

      {open && (
        <div className="ml-3 mt-0.5 border-l border-border/80 pl-3">
      {budgetGauges.length > 0 ? <BudgetTable gauges={budgetGauges} /> : null}
      {Object.keys(data.models).length > 0 &&
        renderTable(t("usage.byModel"), data.models, modelCostCell)}
      {Object.keys(data.categories).length > 0 &&
        renderTable(t("usage.byCategory"), data.categories, categoryCostCell)}
      {lastRequestRows.length > 0 ? (
        <div className="mt-2 text-sm">
          <p className="mb-1 text-xs font-medium text-muted-foreground">
            {t("usage.context")}
          </p>
          <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th className="pb-1 pr-2 font-medium">{t("usage.contextTable.source")}</th>
                <th className="pb-1 pr-2 font-medium text-right">{t("usage.contextTable.tokens")}</th>
                <th className="pb-1 pr-2 font-medium text-right">{t("usage.contextTable.system")}</th>
                <th className="pb-1 pr-2 font-medium text-right">{t("usage.contextTable.user")}</th>
                <th className="pb-1 pr-2 font-medium text-right">
                  {t("usage.contextTable.assistant")}
                </th>
                <th className="pb-1 pr-2 font-medium text-right">
                  {t("usage.contextTable.toolCalls")}
                </th>
                <th className="pb-1 pr-2 font-medium text-right">
                  {t("usage.contextTable.toolOutputs")}
                </th>
                {showOtherPctCol ? (
                  <th className="pb-1 font-medium text-right">{t("usage.contextTable.other")}</th>
                ) : null}
              </tr>
            </thead>
            <tbody>
              {lastRequestRows.map((r) => (
                <tr
                  key={r.source}
                  className="border-b border-border/50 font-mono text-xs"
                >
                  <td className="py-1 pr-2">{r.source}</td>
                  <td className="py-1 pr-2 text-right tabular-nums">
                    {fmt(r.context_size)}
                    {typeof r.context_used_pct === "number" ? (
                      <span className="text-muted-foreground">
                        {" "}
                        ({r.context_used_pct.toFixed(1)}%)
                      </span>
                    ) : null}
                  </td>
                  <td className="py-1 pr-2 text-right tabular-nums">
                    {fmtPctCell(r.breakdown_pct?.system)}
                  </td>
                  <td className="py-1 pr-2 text-right tabular-nums">
                    {fmtPctCell(r.breakdown_pct?.user)}
                  </td>
                  <td className="py-1 pr-2 text-right tabular-nums">
                    {fmtPctCell(r.breakdown_pct?.assistant)}
                  </td>
                  <td className="py-1 pr-2 text-right tabular-nums">
                    {fmtPctCell(r.breakdown_pct?.tool_calls)}
                  </td>
                  <td className="py-1 pr-2 text-right tabular-nums">
                    {fmtPctCell(r.breakdown_pct?.tool_returns)}
                  </td>
                  {showOtherPctCol ? (
                    <td className="py-1 text-right tabular-nums">
                      {fmtPctCell(r.breakdown_pct?.other)}
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </div>
      ) : null}
        </div>
      )}
    </div>
  );
}

function BudgetView({ data }: { data: BudgetPayload }) {
  const t = useTranslations("commandResult");
  if (data.error) {
    return <p className="my-1 text-sm text-destructive">{data.error}</p>;
  }
  if (data.gauges.length === 0) {
    return (
      <div className="my-1 text-sm text-muted-foreground">
        <p>{data.message ?? t("budget.none")}</p>
        {data.usage_hint ? <p className="mt-1 text-xs">{data.usage_hint}</p> : null}
      </div>
    );
  }
  return (
    <div className="my-2 text-sm">
      {data.message ? (
        <p className="mb-2 text-sm text-muted-foreground">{data.message}</p>
      ) : null}
      {data.usage_hint ? (
        <p className="mb-2 text-xs text-muted-foreground">{data.usage_hint}</p>
      ) : null}
      <BudgetTable gauges={data.gauges} />
    </div>
  );
}

function BudgetTable({ gauges }: { gauges: BudgetGauge[] }) {
  const t = useTranslations("commandResult");
  return (
    <div className="my-2 text-sm">
      <p className="mb-1 text-xs font-medium text-muted-foreground">
        {t("budget.title")}
      </p>
      <table className="w-full">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted-foreground">
            <th className="pb-1 pr-3 font-medium">{t("budget.table.metric")}</th>
            <th className="pb-1 pr-3 font-medium text-right">{t("budget.table.current")}</th>
            <th className="pb-1 pr-3 font-medium text-right">{t("budget.table.limit")}</th>
            <th className="pb-1 pr-3 font-medium text-right">{t("budget.table.remaining")}</th>
            <th className="pb-1 font-medium text-right">{t("budget.table.used")}</th>
          </tr>
        </thead>
        <tbody>
          {gauges.map((gauge) => (
            <tr key={gauge.key} className="border-b border-border/50">
              <td
                className="py-1 pr-3 text-xs font-medium"
                title={gauge.key === "equivalent_cost" ? t("budget.equivalentCostHint") : undefined}
              >
                {gauge.label}
              </td>
              <td className="py-1 pr-3 text-xs text-right tabular-nums">
                {gauge.current_value}
              </td>
              <td className="py-1 pr-3 text-xs text-right tabular-nums">
                {gauge.limit_value ?? "—"}
              </td>
              <td className="py-1 pr-3 text-xs text-right tabular-nums">
                {gauge.remaining_value ?? "—"}
              </td>
              <td className="py-1 text-xs text-right tabular-nums">
                {gauge.unavailable_reason ? (
                  <span className="text-destructive">{t("budget.table.blocked")}</span>
                ) : (
                  `${gauge.fill_pct.toFixed(1)}%`
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
