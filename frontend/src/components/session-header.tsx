"use client";

import type { ReactNode } from "react";
import { EmojiText } from "@/components/emoji-text";

/** The session's title and id, with *children* as actions on the right. */
export function SessionHeader({
  sessionId,
  title,
  titleAccessory,
  children,
}: {
  sessionId: string;
  title: string | null | undefined;
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
        <div className="flex shrink-0 items-center gap-2">{children}</div>
      </div>
    </div>
  );
}
