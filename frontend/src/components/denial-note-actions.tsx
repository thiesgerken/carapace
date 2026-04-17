"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";

interface DenialNoteActionsProps {
  allowLabel: string;
  denyLabel?: string;
  noteLabel?: string;
  notePlaceholder: string;
  onAllow: () => void;
  onDeny: (message?: string) => void;
  allowButtonClassName?: string;
  denyButtonClassName?: string;
}

export function DenialNoteActions({
  allowLabel,
  denyLabel = "Deny",
  noteLabel = "Optional note for the agent",
  notePlaceholder,
  onAllow,
  onDeny,
  allowButtonClassName,
  denyButtonClassName,
}: DenialNoteActionsProps) {
  const [message, setMessage] = useState("");
  const [showNote, setShowNote] = useState(false);

  function toggleNote(): void {
    if (showNote) {
      setMessage("");
    }
    setShowNote(!showNote);
  }

  return (
    <div className="mt-3 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={onAllow}
          className={cn(
            "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
            "bg-foreground text-background hover:bg-foreground/90",
            allowButtonClassName,
          )}
        >
          {allowLabel}
        </button>
        <button
          onClick={() =>
            onDeny(showNote ? message.trim() || undefined : undefined)
          }
          className={cn(
            "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
            "border border-destructive/50 text-destructive hover:bg-destructive/10",
            denyButtonClassName,
          )}
        >
          {denyLabel}
        </button>
        <button
          type="button"
          onClick={toggleNote}
          className="text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          {showNote ? "Hide note" : "Add note"}
        </button>
      </div>

      {showNote && (
        <label className="block space-y-1">
          <span className="text-xs text-muted-foreground">{noteLabel}</span>
          <textarea
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            rows={2}
            className={cn(
              "w-full rounded-md border border-border bg-background px-3 py-2 text-xs",
              "text-foreground outline-none transition-colors",
              "focus:border-warning/60 focus:ring-2 focus:ring-warning/20",
            )}
            placeholder={notePlaceholder}
          />
        </label>
      )}
    </div>
  );
}
