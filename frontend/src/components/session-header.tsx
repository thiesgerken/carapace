"use client";

import type { ReactNode } from "react";
import { Bug, MessageSquare } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { EmojiText } from "@/components/emoji-text";
import { cn } from "@/lib/utils";

export type SessionView = "chat" | "debug";

const VIEWS = [
  { view: "chat", icon: MessageSquare, query: "" },
  { view: "debug", icon: Bug, query: "&view=debug" },
] as const;

/** The session's title and id, the Chat | Debug switch, and *children* as further actions on the right. */
export function SessionHeader({
  sessionId,
  title,
  view,
  titleAccessory,
  children,
}: {
  sessionId: string;
  title: string | null | undefined;
  view: SessionView;
  titleAccessory?: ReactNode;
  children?: ReactNode;
}) {
  const trimmedTitle = title?.trim();
  return (
    <div className="border-b border-border px-3 py-2.5 sm:px-4 sm:py-3">
      <div className="flex items-center justify-between gap-3 sm:items-start">
        <div className="min-w-0">
          <div className="flex min-w-0 items-center gap-2">
            <div className="truncate text-sm font-semibold text-foreground">
              {trimmedTitle ? <EmojiText text={trimmedTitle} /> : sessionId}
            </div>
            {titleAccessory}
          </div>
          <div className="mt-1 hidden truncate font-mono text-xs text-muted-foreground sm:block">{sessionId}</div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <SessionViewToggle sessionId={sessionId} view={view} />
          {children}
        </div>
      </div>
    </div>
  );
}

function SessionViewToggle({ sessionId, view }: { sessionId: string; view: SessionView }) {
  const t = useTranslations("sessionView");
  return (
    <nav aria-label={t("label")} className="inline-flex rounded-lg border border-border bg-muted/40 p-0.5">
      {VIEWS.map(({ view: value, icon: Icon, query }) => (
        <Link
          key={value}
          href={`/?session=${encodeURIComponent(sessionId)}${query}`}
          aria-current={value === view ? "page" : undefined}
          title={t(value)}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm transition-colors",
            value === view ? "bg-background font-medium text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
          )}
        >
          <Icon className="h-4 w-4" />
          {/* Icons only on phones, where the header also holds the details button. */}
          <span className="sr-only sm:not-sr-only">{t(value)}</span>
        </Link>
      ))}
    </nav>
  );
}
