"use client";

import { Fragment, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Ban, Loader2, Play, RotateCcw } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { buttonClassName, controlClassName, DetailList, MemoryProvenanceList, PickMatchingRow } from "@/components/memory-ui";
import { MemoryRunDialog } from "@/components/memory-run-dialog";
import { useMemoryStatus } from "@/components/memory-status";
import { cancelMemoryTasks, listMemoryTasks, retryMemoryTasks } from "@/lib/api";
import { formatAbsoluteTime } from "@/lib/format-time";
import {
  formatTokenEstimate,
  formatTokens,
  formatUsd,
  MEMORY_TASK_KINDS,
  MEMORY_TASK_STATUSES,
  toTaskFilter,
  toTaskSelection,
  type TaskFilterForm,
  type TaskPick,
} from "@/lib/memory";
import type { MemoryTaskListResponse, MemoryTaskSelection, MemoryTaskView } from "@/lib/types";
import { cn } from "@/lib/utils";

const NEWEST_BATCH = 50;
const DEFAULT_FORM: TaskFilterForm = { status: "pending", kind: "", period: "", model: "" };
const NO_PICK: TaskPick = { kind: "ids", ids: [] };


function taskModel(task: MemoryTaskView): string | null {
  return task.provenance?.model ?? task.model_override ?? task.estimate?.model ?? null;
}

/** Where the produced record is shown. The Sessions and Timeline tabs read these query params. */
function resultHref(task: MemoryTaskView): string | null {
  if (task.result_id === null) return null;
  switch (task.kind) {
    case "session_extract":
      return `/memory/sessions?session=${encodeURIComponent(task.target)}`;
    case "week_digest":
    case "month_digest":
      return `/memory/timeline?period=${encodeURIComponent(task.target)}`;
    case "mirror":
      return null;
  }
}

export function MemoryTasksView({ server, token }: { server: string; token: string }) {
  const t = useTranslations("memory.tasks");
  const tStatuses = useTranslations("memory.taskStatuses");
  const locale = useLocale();
  const { status, refreshStatus } = useMemoryStatus();
  const [form, setForm] = useState(DEFAULT_FORM);
  const filter = useMemo(() => toTaskFilter(form), [form]);
  const [page, setPage] = useState<MemoryTaskListResponse | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pick, setPick] = useState<TaskPick>(NO_PICK);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [runSelection, setRunSelection] = useState<MemoryTaskSelection | null>(null);
  const [busy, setBusy] = useState(false);

  // `status` is a dependency on purpose: it changes on every poll and after every action.
  // ponytail: a reload drops pages fetched via "Load more"; keep a page count if that annoys.
  useEffect(() => {
    let cancelled = false;
    listMemoryTasks(server, filter)
      .then((result) => {
        if (cancelled) return;
        setPage(result);
        setError(null);
      })
      .catch((listError: unknown) => {
        if (!cancelled) setError(listError instanceof Error ? listError.message : String(listError));
      });
    return () => {
      cancelled = true;
    };
  }, [server, filter, status]);

  const items = page?.items ?? [];
  const total = page?.total ?? 0;
  const visibleIds = items.map((task) => task.id);
  const allVisiblePicked = pick.kind === "matching" || (items.length > 0 && visibleIds.every((id) => pick.ids.includes(id)));
  const pickedCount = pick.kind === "matching" ? total : pick.ids.length;
  const modelOptions = [...new Set([
    ...(status ? Object.values(status.models) : []),
    ...items.map(taskModel).filter((model): model is string => model !== null),
    ...(form.model ? [form.model] : []),
  ])].sort();

  function updateForm(patch: Partial<TaskFilterForm>): void {
    setForm((current) => ({ ...current, ...patch }));
    setPick(NO_PICK);
  }

  function togglePicked(id: number): void {
    setPick((current) => current.kind === "ids"
      ? { kind: "ids", ids: current.ids.includes(id) ? current.ids.filter((picked) => picked !== id) : [...current.ids, id] }
      : current);
  }

  async function loadMore(): Promise<void> {
    if (!page?.next_cursor) return;
    setLoadingMore(true);
    try {
      const next = await listMemoryTasks(server, filter, page.next_cursor);
      setPage({ ...next, items: [...page.items, ...next.items] });
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : String(loadError));
    } finally {
      setLoadingMore(false);
    }
  }

  async function act(action: () => Promise<{ count: number }>, message: (count: number) => string): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      const { count } = await action();
      setNotice(message(count));
      setPick(NO_PICK);
      await refreshStatus();
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : String(actionError));
    } finally {
      setBusy(false);
    }
  }

  function costCell(task: MemoryTaskView): string {
    if (task.provenance) {
      return task.provenance.cost_usd !== null
        ? formatUsd(task.provenance.cost_usd, locale)
        : `${formatTokens(task.provenance.input_tokens, locale)} in · ${formatTokens(task.provenance.output_tokens, locale)} out`;
    }
    if (task.estimate) {
      return task.estimate.cost_usd !== null
        ? `~${formatUsd(task.estimate.cost_usd, locale)}`
        : formatTokenEstimate(task.estimate.input_tokens, task.estimate.output_tokens_cap, locale);
    }
    return "—";
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6">
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <select aria-label={t("filters.status")} value={form.status} onChange={(event) => updateForm({ status: event.target.value as TaskFilterForm["status"] })} className={controlClassName}>
            <option value="">{t("filters.anyStatus")}</option>
            {MEMORY_TASK_STATUSES.map((value) => <option key={value} value={value}>{tStatuses(value)}</option>)}
          </select>
          <select aria-label={t("filters.kind")} value={form.kind} onChange={(event) => updateForm({ kind: event.target.value as TaskFilterForm["kind"] })} className={controlClassName}>
            <option value="">{t("filters.anyKind")}</option>
            {MEMORY_TASK_KINDS.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
          <input
            type="month"
            aria-label={t("filters.month")}
            title={t("filters.month")}
            value={form.period}
            onChange={(event) => updateForm({ period: event.target.value })}
            className={controlClassName}
          />
          <select aria-label={t("filters.model")} value={form.model} onChange={(event) => updateForm({ model: event.target.value })} className={controlClassName}>
            <option value="">{t("filters.anyModel")}</option>
            {modelOptions.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
          <span className="ml-auto text-sm tabular-nums text-muted-foreground">
            {t("matching", { count: total })}
            {page && page.estimate.task_count > 0
              ? ` · ${t("estimate", {
                cost: page.estimate.unpriced_count === page.estimate.task_count
                  ? formatTokenEstimate(page.estimate.input_tokens, page.estimate.output_tokens_cap, locale)
                  : formatUsd(page.estimate.cost_usd, locale),
              })}`
              : null}
          </span>
        </div>

        {error ? <div className="rounded-lg border border-border bg-background px-4 py-2 text-sm text-destructive">{error}</div> : null}
        {notice ? (
          <div className="flex items-center justify-between rounded-lg border border-border bg-background px-4 py-2 text-sm">
            <span>{notice}</span>
            <button type="button" onClick={() => setNotice(null)} className="text-xs text-muted-foreground underline underline-offset-2">{t("dismiss")}</button>
          </div>
        ) : null}

        <div className="overflow-x-auto rounded-lg border border-border bg-background">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-border text-xs text-muted-foreground">
              <tr>
                <th className="w-10 px-3 py-2">
                  <input
                    type="checkbox"
                    aria-label={t("pickPage")}
                    checked={allVisiblePicked}
                    disabled={items.length === 0}
                    onChange={() => setPick(allVisiblePicked ? NO_PICK : { kind: "ids", ids: visibleIds })}
                  />
                </th>
                <th className="px-3 py-2 font-medium">{t("columns.kind")}</th>
                <th className="px-3 py-2 font-medium">{t("columns.target")}</th>
                <th className="px-3 py-2 font-medium">{t("columns.status")}</th>
                <th className="px-3 py-2 font-medium">{t("columns.model")}</th>
                <th className="px-3 py-2 font-medium">{t("columns.version")}</th>
                <th className="px-3 py-2 text-right font-medium">{t("columns.cost")}</th>
                <th className="w-10 px-3 py-2"><span className="sr-only">{t("columns.actions")}</span></th>
              </tr>
              {allVisiblePicked && total > items.length ? (
                <PickMatchingRow
                  colSpan={8}
                  total={total}
                  matching={pick.kind === "matching"}
                  onPickMatching={() => setPick({ kind: "matching" })}
                  onClear={() => setPick(NO_PICK)}
                />
              ) : null}
            </thead>
            <tbody>
              {page === null && error === null ? (
                <tr><td colSpan={8} className="px-3 py-6 text-center text-muted-foreground"><Loader2 className="mx-auto h-4 w-4 animate-spin" /></td></tr>
              ) : items.length === 0 ? (
                <tr><td colSpan={8} className="px-3 py-6 text-center text-muted-foreground">{t("empty")}</td></tr>
              ) : items.map((task) => {
                const expanded = expandedId === task.id;
                return (
                  <Fragment key={task.id}>
                    <tr className={cn("border-b border-border/60 align-top last:border-b-0", expanded && "bg-muted/40")}>
                      <td className="px-3 py-2">
                        <input
                          type="checkbox"
                          aria-label={t("pickTask", { target: task.target_label })}
                          checked={pick.kind === "matching" || pick.ids.includes(task.id)}
                          disabled={pick.kind === "matching"}
                          onChange={() => togglePicked(task.id)}
                        />
                      </td>
                      <td className="px-3 py-2 font-mono text-xs">{task.kind}</td>
                      <td className="px-3 py-2">
                        <button
                          type="button"
                          aria-expanded={expanded}
                          onClick={() => setExpandedId(expanded ? null : task.id)}
                          className="text-left hover:underline"
                        >
                          {task.target_label}
                        </button>
                        {task.status === "failed" && task.error ? (
                          <div className="mt-0.5 line-clamp-1 text-xs text-destructive">{task.error}</div>
                        ) : null}
                      </td>
                      <td className="px-3 py-2">
                        {tStatuses(task.status)}
                        {task.blocked_reason === "budget" ? <div className="text-xs text-amber-700 dark:text-amber-400">{t("blockedBudget")}</div> : null}
                      </td>
                      <td className="px-3 py-2 font-mono text-xs">{taskModel(task) ?? "—"}</td>
                      <td className="px-3 py-2 font-mono text-xs">{task.provenance?.carapace_version ?? "—"}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{costCell(task)}</td>
                      <td className="px-3 py-2">
                        {task.status === "failed" ? (
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => void act(() => retryMemoryTasks(server, [task.id]), (count) => t("retried", { count }))}
                            title={t("retry")}
                            aria-label={t("retry")}
                            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
                          >
                            <RotateCcw className="h-3.5 w-3.5" />
                          </button>
                        ) : null}
                      </td>
                    </tr>
                    {expanded ? (
                      <tr className="border-b border-border/60 bg-muted/40">
                        <td colSpan={8} className="px-3 pb-3">
                          <MemoryTaskDetail task={task} />
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>

        {page?.next_cursor ? (
          <button type="button" onClick={() => void loadMore()} disabled={loadingMore} className={buttonClassName}>
            {loadingMore ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            {t("loadMore")}
          </button>
        ) : null}

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={busy || total === 0}
            onClick={() => setRunSelection({ filter, newest: NEWEST_BATCH })}
            className={buttonClassName}
          >
            <Play className="h-4 w-4" />
            {t("runNewest", { count: NEWEST_BATCH })}
          </button>
          <button
            type="button"
            disabled={busy || pickedCount === 0}
            onClick={() => setRunSelection(toTaskSelection(pick, filter))}
            className={buttonClassName}
          >
            <Play className="h-4 w-4" />
            {t("runPicked", { count: pickedCount })}
          </button>
          <button
            type="button"
            disabled={busy || pickedCount === 0}
            onClick={() => void act(() => cancelMemoryTasks(server, toTaskSelection(pick, filter)), (count) => t("cancelled", { count }))}
            className={buttonClassName}
          >
            <Ban className="h-4 w-4" />
            {t("cancelPicked", { count: pickedCount })}
          </button>
        </div>
      </div>

      {runSelection ? (
        <MemoryRunDialog
          server={server}
          token={token}
          selection={runSelection}
          onClose={() => setRunSelection(null)}
          onQueued={(count) => {
            setNotice(t("queued", { count }));
            setPick(NO_PICK);
            void refreshStatus();
          }}
        />
      ) : null}
    </div>
  );
}

function MemoryTaskDetail({ task }: { task: MemoryTaskView }) {
  const t = useTranslations("memory.tasks.detail");
  const locale = useLocale();
  const time = (iso: string | null) => (iso ? formatAbsoluteTime(iso, locale) : "—");
  const href = resultHref(task);

  return (
    <div className="space-y-2 pt-2 text-xs">
      <DetailList
        rows={[
          [t("id"), String(task.id)],
          [t("spawnedBy"), t(`spawnedByValue.${task.spawned_by}`)],
          [t("attempts"), String(task.attempts)],
          [t("created"), time(task.created_at)],
          [t("queuedAt"), time(task.queued_at)],
          [t("started"), time(task.started_at)],
          [t("finished"), time(task.finished_at)],
          ...(task.estimate && !task.provenance
            ? ([[t("estimate"), `${formatTokens(task.estimate.input_tokens, locale)} in · ≤${formatTokens(task.estimate.output_tokens_cap, locale)} out`]] satisfies [string, string][])
            : []),
        ]}
      />
      {task.provenance ? <MemoryProvenanceList provenance={task.provenance} /> : null}
      {task.error ? <pre className="whitespace-pre-wrap rounded-md bg-background p-2 font-mono text-destructive">{task.error}</pre> : null}
      {href ? <Link href={href} className="inline-block font-medium underline underline-offset-2">{t("openResult")}</Link> : null}
    </div>
  );
}
