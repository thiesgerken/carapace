"use client";

import { X } from "lucide-react";
import { useTranslations } from "next-intl";

/**
 * A short notice with an optional action, bottom right (bottom on a phone), held above the chat composer so it never
 * covers the input. Whoever renders it decides how long it stays.
 */
export function Toast({
  message,
  action,
  onClose,
}: {
  message: string;
  action?: { label: string; onClick: () => void };
  onClose: () => void;
}) {
  const t = useTranslations("toast");
  return (
    <div
      role="status"
      className="fixed inset-x-4 bottom-[calc(env(safe-area-inset-bottom)+6rem)] z-50 flex items-center gap-1 rounded-xl bg-foreground py-1.5 pl-4 pr-1.5 text-sm text-background shadow-lg sm:inset-x-auto sm:right-6 sm:bottom-24 sm:min-w-64"
    >
      <span className="min-w-0 flex-1 truncate">{message}</span>
      {action ? (
        <button
          type="button"
          onClick={action.onClick}
          className="rounded-md px-2.5 py-1.5 font-semibold transition-colors hover:bg-background/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {action.label}
        </button>
      ) : null}
      <button
        type="button"
        onClick={onClose}
        aria-label={t("close")}
        title={t("close")}
        className="rounded-md p-1.5 text-background/70 transition-colors hover:bg-background/15 hover:text-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
