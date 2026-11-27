"use client";

import { ArrowDown, ArrowUp, Check, Download, Loader2, RotateCcw, Upload } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import {
  type GitActionResult,
  getGlobalGit,
  getSandboxGit,
  globalGitPull,
  globalGitPush,
  sandboxGitPull,
  sandboxGitPush,
} from "@/lib/api";
import { cn } from "@/lib/utils";

interface AheadBehindCounts {
  ahead: number | null;
  behind: number | null;
}

// Outcome of the last action/refresh. `detail` holds the raw command output,
// surfaced only as a tooltip; `errorLabel` is the short inline text on failure.
interface ActionOutcome {
  ok: boolean;
  errorLabel: string;
  detail: string;
}

export function AheadBehind({
  counts,
  upToDateLabel,
}: {
  counts: AheadBehindCounts;
  upToDateLabel: string;
}) {
  const ahead = counts.ahead ?? 0;
  const behind = counts.behind ?? 0;
  if (ahead === 0 && behind === 0) {
    return (
      <span className="inline-flex items-center gap-1 text-success">
        <Check className="h-3 w-3 shrink-0" />
        {upToDateLabel}
      </span>
    );
  }
  // Order matches the button row (pull ↓behind, then push ↑ahead).
  return (
    <span className="inline-flex items-center gap-2 font-mono text-foreground">
      <span className={cn("inline-flex items-center gap-0.5", behind > 0 ? "text-info" : "text-muted-foreground")}>
        <ArrowDown className="h-3 w-3 shrink-0" />
        {behind}
      </span>
      <span className={cn("inline-flex items-center gap-0.5", ahead > 0 ? "text-warning" : "text-muted-foreground")}>
        <ArrowUp className="h-3 w-3 shrink-0" />
        {ahead}
      </span>
    </span>
  );
}

/** Shared presentational shell for both git-sync boundaries. */
function GitSyncControls({
  title,
  description,
  counts,
  emptyLabel,
  loading,
  outcome,
  busy,
  disabled,
  pullDisabled,
  pushDisabled,
  pullTitle,
  pushTitle,
  refreshTitle,
  onRefresh,
  onPull,
  onPush,
}: {
  title: string;
  // Explains what this boundary syncs; surfaced as a hover tooltip on the title.
  description: string;
  counts: AheadBehindCounts | null;
  // Shown when there are no counts to display (e.g. no remote). Null hides the
  // line entirely — used on error, where the error label explains the state.
  emptyLabel: string | null;
  loading: boolean;
  outcome: ActionOutcome | null;
  busy: "pull" | "push" | null;
  disabled: boolean;
  pullDisabled: boolean;
  pushDisabled: boolean;
  pullTitle: string;
  pushTitle: string;
  refreshTitle: string;
  onRefresh: () => void;
  onPull: () => void;
  onPush: () => void;
}) {
  const t = useTranslations("git");
  const anyBusy = busy !== null || loading;
  // Raw command output (success or failure) lives only in the status tooltip.
  const detail = outcome?.detail || undefined;
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <div className="cursor-help text-xs text-muted-foreground" title={description}>
          {title}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={onRefresh}
            disabled={disabled || anyBusy}
            title={refreshTitle}
            className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}
          </button>
          <button
            type="button"
            onClick={onPull}
            disabled={disabled || anyBusy || pullDisabled}
            title={pullTitle}
            className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy === "pull" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
          </button>
          <button
            type="button"
            onClick={onPush}
            disabled={disabled || anyBusy || pushDisabled}
            title={pushTitle}
            className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy === "push" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
          </button>
        </div>
      </div>
      {counts ? (
        <div className="text-xs" title={detail}>
          <AheadBehind counts={counts} upToDateLabel={t("upToDate")} />
        </div>
      ) : emptyLabel ? (
        <div className="text-xs text-muted-foreground" title={detail}>
          {emptyLabel}
        </div>
      ) : null}
      {outcome && !outcome.ok ? (
        <div className="truncate text-xs text-destructive" title={detail}>
          {outcome.errorLabel}
        </div>
      ) : null}
    </div>
  );
}

/** B1: sandbox /workspace clone ↔ backend repo. Lives in the chat inspector. */
export function SandboxGitControls({
  server,
  token,
  sessionId,
  disabled = false,
  refreshKey,
}: {
  server: string;
  token: string;
  sessionId: string;
  disabled?: boolean;
  refreshKey?: unknown;
}) {
  const t = useTranslations("git");
  const [counts, setCounts] = useState<AheadBehindCounts | null>(null);
  const [upstream, setUpstream] = useState(true);
  const [running, setRunning] = useState(true);
  const [errored, setErrored] = useState(false);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<"pull" | "push" | null>(null);
  const [outcome, setOutcome] = useState<ActionOutcome | null>(null);

  const refresh = useCallback(
    async (fetch: boolean) => {
      setLoading(true);
      try {
        const status = await getSandboxGit(server, token, sessionId, { fetch });
        setErrored(false);
        setRunning(status.running);
        setUpstream(status.upstream);
        setCounts(status.running ? { ahead: status.ahead, behind: status.behind } : null);
        setOutcome((prev) => (prev && !prev.ok ? null : prev));
      } catch {
        setErrored(true);
        setCounts(null);
        setOutcome({ ok: false, errorLabel: t("errors.status"), detail: "" });
      } finally {
        setLoading(false);
      }
    },
    [server, token, sessionId, t],
  );

  useEffect(() => {
    const id = setTimeout(() => void refresh(true), 0);
    return () => clearTimeout(id);
  }, [refresh, refreshKey]);

  const runAction = useCallback(
    async (action: "pull" | "push", fn: () => Promise<GitActionResult>) => {
      setBusy(action);
      setOutcome(null);
      try {
        const result = await fn();
        await refresh(true);
        setOutcome({
          ok: result.ok,
          errorLabel: result.denied ? t("denied") : t(`errors.${action}`),
          detail: result.message,
        });
      } catch {
        setOutcome({ ok: false, errorLabel: t(`errors.${action}`), detail: "" });
      } finally {
        setBusy(null);
      }
    },
    [refresh, t],
  );

  return (
    <GitSyncControls
      title={t("sandbox.label")}
      description={t("sandbox.help")}
      counts={running && upstream ? counts : null}
      emptyLabel={errored ? null : !running ? t("sandbox.notRunning") : t("noRemote")}
      loading={loading}
      outcome={outcome}
      busy={busy}
      disabled={disabled || !running}
      pullDisabled={!upstream || (counts?.behind ?? 0) === 0}
      pushDisabled={!upstream || (counts?.ahead ?? 0) === 0}
      pullTitle={t("sandbox.pull")}
      pushTitle={t("sandbox.push")}
      refreshTitle={t("sandbox.refresh")}
      onRefresh={() => void refresh(true)}
      onPull={() => void runAction("pull", () => sandboxGitPull(server, token, sessionId))}
      onPush={() => void runAction("push", () => sandboxGitPush(server, token, sessionId))}
    />
  );
}

// B2: backend per-user repo ↔ external remote. Shown by the sidebar's sync row and
// the knowledge browser's panel.

/**
 * Fired after a pull or push moves the knowledge repo. Listened to by every
 * `useGlobalGit` instance, and by views showing repo contents.
 */
export const KNOWLEDGE_GIT_CHANGED_EVENT = "carapace:knowledge-git-changed";

const GLOBAL_GIT_ACTIONS = { pull: globalGitPull, push: globalGitPush } as const;

export interface GlobalGit {
  configured: boolean | null;
  counts: AheadBehindCounts | null;
  head: { hash: string; subject: string } | null;
  loading: boolean;
  busy: "pull" | "push" | null;
  outcome: ActionOutcome | null;
  refresh: () => void;
  pull: () => void;
  push: () => void;
  /** Pull, then push if the pull went through: brings a diverged repo back in sync in one step. */
  sync: () => void;
}

export function useGlobalGit(server: string, token: string): GlobalGit {
  const t = useTranslations("git");
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [counts, setCounts] = useState<AheadBehindCounts | null>(null);
  const [head, setHead] = useState<{ hash: string; subject: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<"pull" | "push" | null>(null);
  // Kept apart from the action outcome: a re-read clears its own failure, but never a
  // failed pull or push, which stays until the next action.
  const [statusFailed, setStatusFailed] = useState(false);
  const [outcome, setOutcome] = useState<ActionOutcome | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const status = await getGlobalGit(server, token);
      setConfigured(status.remote_configured);
      setCounts(status.remote_configured ? { ahead: status.ahead, behind: status.behind } : null);
      setHead(status.head ? { hash: status.head, subject: status.head_subject ?? "" } : null);
      setStatusFailed(false);
    } catch {
      setCounts(null);
      setHead(null);
      setStatusFailed(true);
    } finally {
      setLoading(false);
    }
  }, [server, token]);

  useEffect(() => {
    const id = setTimeout(() => void refresh(), 0);
    return () => clearTimeout(id);
  }, [refresh]);

  // Several of these hooks are mounted at once (the sidebar sync row, the knowledge
  // browser). A refresh, pull or push from any of them changes what all of them should
  // show, so they re-read status together instead of the others going stale until remount.
  useEffect(() => {
    const onChanged = () => void refresh();
    window.addEventListener(KNOWLEDGE_GIT_CHANGED_EVENT, onChanged);
    return () => window.removeEventListener(KNOWLEDGE_GIT_CHANGED_EVENT, onChanged);
  }, [refresh]);

  // Runs the actions in order and stops at the first failure. `busy` stays set throughout,
  // and status is re-read once at the end: a re-read between steps would race the next one.
  const runActions = useCallback(
    async (actions: readonly (keyof typeof GLOBAL_GIT_ACTIONS)[]) => {
      setOutcome(null);
      let moved = false;
      try {
        for (const action of actions) {
          setBusy(action);
          const result = await GLOBAL_GIT_ACTIONS[action](server, token).catch(() => null);
          setOutcome({ ok: result?.ok ?? false, errorLabel: t(`errors.${action}`), detail: result?.message ?? "" });
          if (!result?.ok) return;
          moved = true;
        }
      } finally {
        setBusy(null);
        // Every mounted panel re-reads status off this, the acting one included, so
        // there is no refresh() call here — it would fetch the same status twice.
        if (moved) window.dispatchEvent(new Event(KNOWLEDGE_GIT_CHANGED_EVENT));
      }
    },
    [server, token, t],
  );

  return {
    configured,
    counts,
    head,
    loading,
    busy,
    outcome: outcome && !outcome.ok ? outcome : statusFailed ? { ok: false, errorLabel: t("errors.status"), detail: "" } : outcome,
    // Through the event, like pull and push: the acting instance re-reads via its own listener.
    refresh: () => { window.dispatchEvent(new Event(KNOWLEDGE_GIT_CHANGED_EVENT)); },
    pull: () => void runActions(["pull"]),
    push: () => void runActions(["push"]),
    sync: () => void runActions(["pull", "push"]),
  };
}

/** Full git panel for the knowledge browser, shown even without a remote so the refresh control stays reachable. */
export function GlobalGitPanel({ git, className }: { git: GlobalGit; className?: string }) {
  const t = useTranslations("git");
  return (
    <div className={className}>
      <GitSyncControls
        title={t("global.label")}
        description={t("global.help")}
        counts={git.counts}
        emptyLabel={git.configured === false ? t("noRemote") : null}
        loading={git.loading}
        outcome={git.outcome}
        busy={git.busy}
        disabled={false}
        pullDisabled={(git.counts?.behind ?? 0) === 0}
        pushDisabled={(git.counts?.ahead ?? 0) === 0}
        pullTitle={t("global.pull")}
        pushTitle={t("global.push")}
        refreshTitle={t("global.refresh")}
        onRefresh={git.refresh}
        onPull={git.pull}
        onPush={git.push}
      />
    </div>
  );
}
