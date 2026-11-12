"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, Shrink } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { fetchCompactionPreview, type CompactionPreviewInfo } from "@/lib/api";
import { formatTokens } from "@/lib/memory";

interface CompactionDialogProps {
  server: string;
  token: string;
  sessionId: string;
  onClose: () => void;
  onCompact: (focus: string) => void;
  onUncompact: () => void;
}

type PreviewOutcome = { preview: CompactionPreviewInfo } | { error: string };

/** Dry run of `/compact` (no LLM call), with an optional focus for the summaries. */
export function CompactionDialog({ server, token, sessionId, onClose, onCompact, onUncompact }: CompactionDialogProps) {
  const t = useTranslations("chatView.compaction");
  const locale = useLocale();
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const [outcome, setOutcome] = useState<PreviewOutcome | null>(null);
  const [focus, setFocus] = useState("");

  useEffect(() => {
    dialogRef.current?.showModal();
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchCompactionPreview(server, token, sessionId)
      .then((preview) => {
        if (!cancelled) setOutcome({ preview });
      })
      .catch((loadError: unknown) => {
        if (!cancelled) setOutcome({ error: loadError instanceof Error ? loadError.message : String(loadError) });
      });
    return () => {
      cancelled = true;
    };
  }, [server, token, sessionId]);

  const preview = outcome && "preview" in outcome ? outcome.preview : null;
  const tokens = (value: number) => formatTokens(value, locale);
  const nothing = preview !== null && !preview.thinking_dropped && !preview.turns_folded && preview.tool_outputs.length === 0;

  function close(): void {
    dialogRef.current?.close();
  }

  return (
    <dialog
      ref={dialogRef}
      onClose={onClose}
      aria-labelledby="compaction-dialog-title"
      className="m-auto w-[min(32rem,calc(100vw-2rem))] overflow-visible rounded-2xl border border-border bg-background p-0 text-foreground shadow-xl backdrop:bg-black/40"
    >
      <div className="space-y-4 p-5">
        <h2 id="compaction-dialog-title" className="text-lg font-semibold tracking-tight">{t("title")}</h2>

        {outcome === null ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t("loading")}
          </div>
        ) : "error" in outcome ? (
          <p className="text-sm text-destructive">{outcome.error}</p>
        ) : (
          <>
            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5 text-sm">
              <dt className="text-muted-foreground">{t("context")}</dt>
              <dd className="tabular-nums">{tokens(outcome.preview.context_tokens)}</dd>
              <dt className="text-muted-foreground">{t("threshold")}</dt>
              <dd className="tabular-nums">{tokens(outcome.preview.threshold_tokens)}</dd>
              <dt className="text-muted-foreground">{t("window")}</dt>
              <dd className="tabular-nums">{tokens(outcome.preview.context_window_tokens)}</dd>
            </dl>

            {nothing ? (
              <p className="text-sm text-muted-foreground">{t("nothing")}</p>
            ) : (
              <div className="space-y-1.5 text-sm">
                <div className="text-xs font-medium text-muted-foreground">{t("plan")}</div>
                <ul className="list-inside list-disc space-y-0.5">
                  {outcome.preview.thinking_dropped ? <li>{t("thinking", { count: outcome.preview.thinking_dropped })}</li> : null}
                  {outcome.preview.turns_folded ? (
                    <li>{t("fold", { count: outcome.preview.turns_folded, tokens: tokens(outcome.preview.fold_tokens) })}</li>
                  ) : null}
                  {outcome.preview.tool_outputs.map((output, index) => (
                    <li key={index}>{t("toolOutput", { tool: output.tool_name, tokens: tokens(output.tokens) })}</li>
                  ))}
                </ul>
                <p className="text-muted-foreground">
                  {t("estimate", { tokens: tokens(outcome.preview.estimated_tokens_without_summaries) })}
                </p>
              </div>
            )}
          </>
        )}

        <label className="block space-y-1.5">
          <span className="text-xs font-medium text-muted-foreground">{t("focus")}</span>
          <input
            type="text"
            value={focus}
            onChange={(event) => setFocus(event.target.value)}
            placeholder={t("focusPlaceholder")}
            className="h-10 w-full rounded-lg border border-border bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
          />
        </label>

        <details className="text-sm">
          <summary className="cursor-pointer text-xs font-medium text-muted-foreground">{t("debug")}</summary>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
            <span className="text-muted-foreground">{t("uncompactHint")}</span>
            <button
              type="button"
              onClick={() => {
                onUncompact();
                close();
              }}
              className="rounded-md px-2 py-1 font-medium underline underline-offset-2 hover:bg-muted"
            >
              {t("uncompact")}
            </button>
          </div>
        </details>

        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={close}
            className="rounded-lg px-4 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            {t("cancel")}
          </button>
          <button
            type="button"
            onClick={() => {
              onCompact(focus.trim());
              close();
            }}
            disabled={nothing}
            className="inline-flex items-center gap-2 rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-background transition-colors hover:bg-foreground/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Shrink className="h-4 w-4" />
            {t("run")}
          </button>
        </div>
      </div>
    </dialog>
  );
}
