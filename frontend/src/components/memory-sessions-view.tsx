"use client";

import { Fragment, useEffect, useMemo, useState, type MouseEvent } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ChevronRight, Loader2, MessageSquare, Play, RefreshCw } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { MemoryExtractionDetail, useMemorySessionDetail } from "@/components/memory-extraction-detail";
import { MemoryRunDialog } from "@/components/memory-run-dialog";
import { useMemoryStatus } from "@/components/memory-status";
import { buttonClassName, controlClassName, PickMatchingRow } from "@/components/memory-ui";
import { listMemorySessions, spawnMemoryTasks } from "@/lib/api";
import {
  formatUsd,
  MEMORY_EXTRACTION_STATES,
  MEMORY_OUTDATED_REASONS,
  MEMORY_TASK_STATUSES,
  runnableTaskIds,
  summarizeSkips,
  toSessionFilter,
  toSpawnRequest,
  type SessionFilterForm,
  type SessionPick,
} from "@/lib/memory";
import type { MemorySessionListResponse, MemorySessionRow, MemoryTaskSelection } from "@/lib/types";
import { cn } from "@/lib/utils";

const DEFAULT_FORM: SessionFilterForm = { week: "", state: "", outdatedReason: "", taskStatus: "", model: "", channel: "" };
const NO_PICK: SessionPick = { kind: "ids", ids: [] };
const COLUMNS = 8;

export function MemorySessionsView({ server, token }: { server: string; token: string }) {
  const t = useTranslations("memory.sessions");
  const tStatuses = useTranslations("memory.taskStatuses");
  const tReasons = useTranslations("memory.outdatedReasons");
  const locale = useLocale();
  const router = useRouter();
  const pathname = usePathname();
  // The expanded row lives in the URL, so /memory/sessions?session=… deep links open it.
  const expandedId = useSearchParams().get("session");
  const { status, refreshStatus } = useMemoryStatus();
  // Polled with the rows, so the expanded detail never lags behind its live row.
  const expanded = useMemorySessionDetail(server, expandedId, status);
  const [form, setForm] = useState(DEFAULT_FORM);
  const filter = useMemo(() => toSessionFilter(form), [form]);
  const [page, setPage] = useState<MemorySessionListResponse | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pick, setPick] = useState<SessionPick>(NO_PICK);
  const [runSelection, setRunSelection] = useState<MemoryTaskSelection | null>(null);
  const [busy, setBusy] = useState(false);

  // `status` changes on every poll and after every action; see MemoryStatusProvider.
  useEffect(() => {
    let cancelled = false;
    listMemorySessions(server, filter)
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

  const loadedRows = page?.items ?? [];
  // A deep-linked session outside the loaded page or filter is pinned on top, so it can still expand.
  const pinnedRow = expanded.detail && !loadedRows.some((row) => row.session_id === expandedId) ? expanded.detail.session : null;
  const rows = pinnedRow ? [pinnedRow, ...loadedRows] : loadedRows;
  const total = page?.total ?? 0;
  const visibleIds = rows.map((row) => row.session_id);
  const allVisiblePicked = pick.kind === "matching" || (rows.length > 0 && visibleIds.every((id) => pick.ids.includes(id)));
  const pickedCount = pick.kind === "matching" ? total : pick.ids.length;
  const taskIds = pick.kind === "ids" ? runnableTaskIds(rows, pick.ids) : [];
  const options = (values: (string | null | undefined)[], current: string) =>
    [...new Set([...values, current].filter((value): value is string => !!value))].sort();
  const modelOptions = options([...(status ? Object.values(status.models) : []), ...rows.map((row) => row.extraction?.model)], form.model);
  const channelOptions = options(rows.map((row) => row.channel_type), form.channel);

  function updateForm(patch: Partial<SessionFilterForm>): void {
    setForm((current) => ({ ...current, ...patch }));
    setPick(NO_PICK);
  }

  function togglePicked(id: string): void {
    setPick((current) => current.kind === "ids"
      ? { kind: "ids", ids: current.ids.includes(id) ? current.ids.filter((picked) => picked !== id) : [...current.ids, id] }
      : current);
  }

  function toggleExpanded(sessionId: string): void {
    router.replace(sessionId === expandedId ? pathname : `${pathname}?session=${encodeURIComponent(sessionId)}`, { scroll: false });
  }

  /** Clicking empty row space toggles too; the checkbox, links and buttons keep their own action. */
  function handleRowClick(event: MouseEvent<HTMLTableRowElement>, sessionId: string): void {
    if ((event.target as HTMLElement).closest("a, button, input, label")) return;
    toggleExpanded(sessionId);
  }

  const expandedRowPresent = rows.some((row) => row.session_id === expandedId);
  useEffect(() => {
    if (expandedId && expandedRowPresent) document.getElementById(sessionRowId(expandedId))?.scrollIntoView({ block: "nearest" });
  }, [expandedId, expandedRowPresent]);

  async function loadMore(): Promise<void> {
    if (!page?.next_cursor) return;
    setLoadingMore(true);
    try {
      const next = await listMemorySessions(server, filter, page.next_cursor);
      setPage({ ...next, items: [...page.items, ...next.items] });
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : String(loadError));
    } finally {
      setLoadingMore(false);
    }
  }

  /** Respawned tasks start pending; the run dialog then offers the estimate and model override. */
  async function respawn(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      const { task_ids, skipped } = await spawnMemoryTasks(server, toSpawnRequest(pick, filter));
      setNotice(
        skipped.length > 0
          ? t("spawnedWithSkips", { count: task_ids.length, reasons: summarizeSkips(skipped) })
          : t("spawned", { count: task_ids.length }),
      );
      setPick(NO_PICK);
      if (task_ids.length > 0) setRunSelection({ ids: task_ids });
      await refreshStatus();
    } catch (spawnError) {
      setError(spawnError instanceof Error ? spawnError.message : String(spawnError));
    } finally {
      setBusy(false);
    }
  }

  function statusCell(row: MemorySessionRow) {
    const extraction = row.extraction;
    const state = extraction === null ? "missing" : extraction.outdated.length > 0 ? "outdated" : "current";
    return (
      <>
        <div className={cn(state === "current" && "text-[#236b86]", state === "outdated" && "text-amber-700 dark:text-amber-400")}>
          {t(`states.${state}`)}
        </div>
        {extraction && extraction.outdated.length > 0 ? (
          <div className="text-xs text-muted-foreground">{extraction.outdated.map((reason) => tReasons(reason)).join(", ")}</div>
        ) : null}
        {row.task && row.task.status !== "done" ? (
          <div className="text-xs text-muted-foreground">
            {t("task", { status: tStatuses(row.task.status) })}
            {row.task.blocked_reason === "budget" ? ` ⏸` : null}
          </div>
        ) : null}
      </>
    );
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6">
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="week"
            aria-label={t("filters.week")}
            title={t("filters.week")}
            value={form.week}
            onChange={(event) => updateForm({ week: event.target.value })}
            className={controlClassName}
          />
          <select aria-label={t("filters.state")} value={form.state} onChange={(event) => updateForm({ state: event.target.value as SessionFilterForm["state"] })} className={controlClassName}>
            <option value="">{t("filters.anyState")}</option>
            {MEMORY_EXTRACTION_STATES.map((value) => <option key={value} value={value}>{t(`states.${value}`)}</option>)}
          </select>
          <select
            aria-label={t("filters.reason")}
            value={form.outdatedReason}
            disabled={form.state !== "outdated"}
            onChange={(event) => updateForm({ outdatedReason: event.target.value as SessionFilterForm["outdatedReason"] })}
            className={controlClassName}
          >
            <option value="">{t("filters.anyReason")}</option>
            {MEMORY_OUTDATED_REASONS.map((value) => <option key={value} value={value}>{tReasons(value)}</option>)}
          </select>
          <select aria-label={t("filters.taskStatus")} value={form.taskStatus} onChange={(event) => updateForm({ taskStatus: event.target.value as SessionFilterForm["taskStatus"] })} className={controlClassName}>
            <option value="">{t("filters.anyTaskStatus")}</option>
            {MEMORY_TASK_STATUSES.map((value) => <option key={value} value={value}>{tStatuses(value)}</option>)}
          </select>
          <select aria-label={t("filters.model")} value={form.model} onChange={(event) => updateForm({ model: event.target.value })} className={controlClassName}>
            <option value="">{t("filters.anyModel")}</option>
            {modelOptions.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
          <select aria-label={t("filters.channel")} value={form.channel} onChange={(event) => updateForm({ channel: event.target.value })} className={controlClassName}>
            <option value="">{t("filters.anyChannel")}</option>
            {channelOptions.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
          <span className="ml-auto text-sm tabular-nums text-muted-foreground">{t("matching", { count: total })}</span>
          <button
            type="button"
            disabled={busy || taskIds.length === 0}
            onClick={() => setRunSelection({ ids: taskIds })}
            title={pick.kind === "matching" ? t("runNeedsRows") : undefined}
            className={buttonClassName}
          >
            <Play className="h-4 w-4" />
            {t("runPicked", { count: taskIds.length })}
          </button>
          <button type="button" disabled={busy || pickedCount === 0} onClick={() => void respawn()} className={buttonClassName}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            {t("respawnPicked", { count: pickedCount })}
          </button>
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
                    disabled={rows.length === 0}
                    onChange={() => setPick(allVisiblePicked ? NO_PICK : { kind: "ids", ids: visibleIds })}
                  />
                </th>
                <th className="px-3 py-2 font-medium">{t("columns.date")}</th>
                <th className="px-3 py-2 font-medium">{t("columns.title")}</th>
                <th className="px-3 py-2 font-medium" title={t("columns.factsHint")}>{t("columns.facts")}</th>
                <th className="px-3 py-2 font-medium">{t("columns.model")}</th>
                <th className="px-3 py-2 font-medium">{t("columns.status")}</th>
                <th className="px-3 py-2 text-right font-medium">{t("columns.cost")}</th>
                <th className="w-10 px-3 py-2"><span className="sr-only">{t("columns.details")}</span></th>
              </tr>
              {allVisiblePicked && total > rows.length ? (
                <PickMatchingRow
                  colSpan={COLUMNS}
                  total={total}
                  matching={pick.kind === "matching"}
                  onPickMatching={() => setPick({ kind: "matching" })}
                  onClear={() => setPick(NO_PICK)}
                />
              ) : null}
            </thead>
            <tbody>
              {page === null && error === null ? (
                <tr><td colSpan={COLUMNS} className="px-3 py-6 text-center text-muted-foreground"><Loader2 className="mx-auto h-4 w-4 animate-spin" /></td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={COLUMNS} className="px-3 py-6 text-center text-muted-foreground">{t("empty")}</td></tr>
              ) : rows.map((row) => {
                const counts = row.extraction?.fact_counts;
                const isExpanded = row.session_id === expandedId;
                const title = row.title?.trim() || t("untitled");
                return (
                  <Fragment key={row.session_id}>
                    <tr
                      id={sessionRowId(row.session_id)}
                      onClick={(event) => handleRowClick(event, row.session_id)}
                      className={cn("cursor-pointer border-b border-border/60 align-top last:border-b-0 hover:bg-muted/30", isExpanded && "bg-muted/40")}
                    >
                      <td className="px-3 py-2">
                        <input
                          type="checkbox"
                          aria-label={t("pickSession", { title: row.title ?? row.session_id })}
                          checked={pick.kind === "matching" || pick.ids.includes(row.session_id)}
                          disabled={pick.kind === "matching"}
                          onChange={() => togglePicked(row.session_id)}
                        />
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 tabular-nums">
                        {new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(Date.parse(row.created_at))}
                      </td>
                      <td className="max-w-md px-3 py-2">
                        <div className="flex items-start gap-1.5">
                          <span className="font-medium">{title}</span>
                          <Link
                            href={`/?session=${encodeURIComponent(row.session_id)}`}
                            aria-label={t("openChat", { title })}
                            title={t("openChat", { title })}
                            className="mt-0.5 shrink-0 text-muted-foreground hover:text-foreground"
                          >
                            <MessageSquare className="h-3.5 w-3.5" />
                          </Link>
                        </div>
                        {row.extraction ? <div className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{row.extraction.abstract}</div> : null}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 tabular-nums">{counts ? `${counts.user}·${counts.social}·${counts.surroundings}` : "—"}</td>
                      <td className="px-3 py-2 font-mono text-xs">{row.extraction?.model ?? "—"}</td>
                      <td className="px-3 py-2">{statusCell(row)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {row.extraction?.cost_usd != null ? formatUsd(row.extraction.cost_usd, locale) : "—"}
                      </td>
                      <td className="px-3 py-1.5">
                        <button
                          type="button"
                          onClick={() => toggleExpanded(row.session_id)}
                          aria-expanded={isExpanded}
                          aria-controls={isExpanded ? sessionDetailId(row.session_id) : undefined}
                          aria-label={t(isExpanded ? "collapse" : "expand", { title })}
                          className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
                        >
                          <ChevronRight className={cn("h-4 w-4 transition-transform", isExpanded && "rotate-90")} />
                        </button>
                      </td>
                    </tr>
                    {isExpanded ? (
                      <tr id={sessionDetailId(row.session_id)} className="border-b border-border/60 bg-muted/40 last:border-b-0">
                        <td colSpan={COLUMNS} className="px-5 pb-5 pt-2">
                          <MemoryExtractionDetail sessionId={row.session_id} state={expanded} />
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
      </div>

      {runSelection ? (
        <MemoryRunDialog
          server={server}
          token={token}
          selection={runSelection}
          kinds={["session_extract"]}
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

function sessionRowId(sessionId: string): string {
  return `memory-session-${sessionId}`;
}

function sessionDetailId(sessionId: string): string {
  return `memory-session-detail-${sessionId}`;
}
