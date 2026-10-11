"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { MessageSquare, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { MemoryExtractionDetail, useMemorySessionDetail } from "@/components/memory-extraction-detail";

interface MemoryExtractionDrawerProps {
  server: string;
  sessionId: string;
  onClose: () => void;
  /** Called when a fact source link is followed. A drawer over the linked chat closes here;
   * elsewhere the navigation unmounts it, and closing first would race the navigation. */
  onSourceNavigate?: () => void;
}

export function MemoryExtractionDrawer({ server, sessionId, onClose, onSourceNavigate }: MemoryExtractionDrawerProps) {
  const t = useTranslations("memory.drawer");
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const state = useMemorySessionDetail(server, sessionId);

  useEffect(() => {
    dialogRef.current?.showModal();
  }, []);

  const title = state.detail?.session.title?.trim() || sessionId;

  return (
    <dialog
      ref={dialogRef}
      onClose={onClose}
      aria-labelledby="memory-drawer-title"
      className="m-0 ml-auto h-dvh max-h-none w-[min(40rem,100vw)] max-w-none border-l border-border bg-background p-0 text-foreground shadow-xl backdrop:bg-black/40"
    >
      <div className="flex h-full flex-col">
        <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <h2 id="memory-drawer-title" className="truncate text-lg font-semibold tracking-tight">{title}</h2>
            <Link href={`/?session=${encodeURIComponent(sessionId)}`} className="mt-1 inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground">
              <MessageSquare className="h-3.5 w-3.5" />
              {t("openSession")}
            </Link>
          </div>
          <button
            type="button"
            onClick={() => dialogRef.current?.close()}
            aria-label={t("close")}
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <MemoryExtractionDetail sessionId={sessionId} state={state} onSourceNavigate={onSourceNavigate} />
        </div>
      </div>
    </dialog>
  );
}
