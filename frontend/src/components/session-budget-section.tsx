"use client";

import { Loader2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useState, type KeyboardEvent } from "react";

import { formatUsd } from "@/lib/memory";
import type { SessionBudgetSettings } from "@/lib/types";

export type SessionBudgetField = keyof SessionBudgetSettings;

const BUDGET_FIELDS: SessionBudgetField[] = [
  "input_tokens",
  "output_tokens",
  "cost_usd",
  "tool_calls",
  "autonomous_tool_calls",
];

function rawLimit(budget: SessionBudgetSettings, field: SessionBudgetField): string {
  const value = budget[field];
  return value == null ? "" : String(value);
}

function formatLimit(budget: SessionBudgetSettings, field: SessionBudgetField, locale: string): string | null {
  const value = budget[field];
  if (value == null) return null;
  return field === "cost_usd" ? formatUsd(value, locale) : new Intl.NumberFormat(locale).format(Number(value));
}

interface SessionBudgetSectionProps {
  budget: SessionBudgetSettings;
  disabled: boolean;
  /** `null` clears the limit. The value is sent as typed, the server parses it like `/budget`. */
  onSave: (field: SessionBudgetField, value: string | null) => Promise<void>;
}

export function SessionBudgetSection({ budget, disabled, onSave }: SessionBudgetSectionProps) {
  const t = useTranslations("chatView.budget");
  const locale = useLocale();
  const [editing, setEditing] = useState<{ field: SessionBudgetField; draft: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function startEditing(field: SessionBudgetField) {
    setError(null);
    setEditing({ field, draft: rawLimit(budget, field) });
  }

  function cancelEditing() {
    setError(null);
    setEditing(null);
  }

  async function commit() {
    // Enter saves and the input then blurs, which would commit a second time.
    if (!editing || saving) return;
    const draft = editing.draft.trim();
    if (draft === rawLimit(budget, editing.field)) {
      cancelEditing();
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSave(editing.field, draft === "" ? null : draft);
      setEditing(null);
    } catch (err) {
      setError(err instanceof Error && err.message.trim() ? err.message : t("saveFailed"));
    } finally {
      setSaving(false);
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault();
      void commit();
    } else if (event.key === "Escape") {
      event.preventDefault();
      cancelEditing();
    }
  }

  return (
    <section className="rounded-2xl border border-border/70 bg-background/90 p-3 shadow-sm">
      <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
        {t("title")}
      </div>

      <dl className="mt-3 grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1.5 text-sm">
        {BUDGET_FIELDS.map((field) => {
          const label = t(`fields.${field}`);
          const limit = formatLimit(budget, field, locale);
          return (
            <div key={field} className="contents">
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="flex items-center justify-end gap-1.5">
                {editing?.field === field ? (
                  <>
                    {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" /> : null}
                    <input
                      autoFocus
                      type="text"
                      inputMode="decimal"
                      value={editing.draft}
                      placeholder={t("noLimit")}
                      aria-label={t("editLimit", { label })}
                      disabled={saving}
                      onChange={(event) => setEditing({ field, draft: event.target.value })}
                      onKeyDown={handleKeyDown}
                      onBlur={() => void commit()}
                      className="w-28 rounded-md border border-border bg-background px-2 py-0.5 text-right text-sm tabular-nums focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
                    />
                  </>
                ) : (
                  <button
                    type="button"
                    onClick={() => startEditing(field)}
                    disabled={disabled || editing !== null}
                    aria-label={t("editLimit", { label })}
                    className="rounded-md px-1.5 py-0.5 text-right tabular-nums transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {limit ?? <span className="text-muted-foreground">{t("noLimit")}</span>}
                  </button>
                )}
              </dd>
            </div>
          );
        })}
      </dl>

      {error ? <div className="mt-2 text-xs text-destructive">{error}</div> : null}
      <div className="mt-2 text-xs text-muted-foreground">{t("hint")}</div>
    </section>
  );
}
