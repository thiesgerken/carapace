"use client";

import { BookOpen, Bot, Eye, Lock, MessageSquare, PencilLine, ShieldCheck, Zap } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { SwitchRow } from "@/components/switch-row";
import { cn } from "@/lib/utils";

export type SessionOptionKey = "private" | "ask_mode" | "yolo_mode" | "unattended";

export interface SessionOptionTileItem {
  key: SessionOptionKey;
  active: boolean;
  disabled?: boolean;
  onClick?: () => void;
}

export const SESSION_OPTION_ORDER: SessionOptionKey[] = [
  "private",
  "ask_mode",
  "yolo_mode",
  "unattended",
];

function getOptionCopy(
  t: ReturnType<typeof useTranslations<"newSessionButton">>,
  key: SessionOptionKey,
  active: boolean,
): { title: string; description: string } {
  switch (key) {
    case "private":
      return active
        ? {
            title: t("private.enabledTitle"),
            description: t("private.enabledDescription"),
          }
        : {
            title: t("private.disabledTitle"),
            description: t("private.disabledDescription"),
          };
    case "ask_mode":
      return active
        ? {
            title: t("ask.enabledTitle"),
            description: t("ask.enabledDescription"),
          }
        : {
            title: t("ask.disabledTitle"),
            description: t("ask.disabledDescription"),
          };
    case "yolo_mode":
      return active
        ? {
            title: t("yolo.enabledTitle"),
            description: t("yolo.enabledDescription"),
          }
        : {
            title: t("yolo.disabledTitle"),
            description: t("yolo.disabledDescription"),
          };
    case "unattended":
      return active
        ? {
            title: t("unattended.enabledTitle"),
            description: t("unattended.enabledDescription"),
          }
        : {
            title: t("unattended.disabledTitle"),
            description: t("unattended.disabledDescription"),
          };
  }
}

function getOptionIcon(key: SessionOptionKey, active: boolean): LucideIcon {
  switch (key) {
    case "private":
      return active ? Lock : BookOpen;
    case "ask_mode":
      return active ? Eye : PencilLine;
    case "yolo_mode":
      return active ? Zap : ShieldCheck;
    case "unattended":
      return active ? Bot : MessageSquare;
  }
}

/** Whether *key* switched on lowers a safeguard, which the active state then shows as a warning. */
function lowersSafeguard(key: SessionOptionKey): boolean {
  // YOLO switches off the sentinel review.
  return key === "yolo_mode";
}

function getOptionClasses(key: SessionOptionKey, active: boolean, disabled: boolean): string {
  if (disabled) {
    return active ? "border-border bg-muted text-foreground/70" : "border-border/60 text-muted-foreground";
  }

  if (!active) {
    return "border-border text-foreground hover:bg-muted";
  }

  return lowersSafeguard(key)
    ? "border-warning/50 bg-warning/10 text-foreground hover:bg-warning/15"
    : "border-primary/50 bg-primary/10 text-foreground hover:bg-primary/15";
}

interface SessionOptionTilesProps {
  items: SessionOptionTileItem[];
  className?: string;
}

export function SessionOptionTiles({ items, className }: SessionOptionTilesProps) {
  const t = useTranslations("newSessionButton");

  return (
    <div className={cn("grid grid-cols-2 gap-2", className)}>
      {items.map((item) => {
        const active = item.active;
        const disabled = item.disabled ?? false;
        const copy = getOptionCopy(t, item.key, active);
        const Icon = getOptionIcon(item.key, active);

        return (
          <button
            key={item.key}
            type="button"
            aria-pressed={active}
            disabled={disabled}
            onClick={item.onClick}
            className={cn(
              "flex min-h-[7rem] w-full flex-col items-start justify-start rounded-xl border px-3 py-3 text-left transition-colors",
              disabled && "cursor-not-allowed",
              getOptionClasses(item.key, active, disabled),
            )}
          >
            <span className="flex items-center gap-2 text-sm font-medium">
              <Icon className="h-4 w-4 shrink-0" />
              <span>{copy.title}</span>
            </span>
            <span
              className={cn(
                "mt-1 block min-h-[2.5rem] overflow-hidden text-xs leading-5 [display:-webkit-box] [-webkit-box-orient:vertical] [-webkit-line-clamp:2]",
                active ? "text-current/80" : "text-muted-foreground",
                disabled && "text-current/70",
              )}
            >
              {copy.description}
            </span>
          </button>
        );
      })}
    </div>
  );
}

/**
 * The same options as compact switches, for the chat inspector. A switch is labelled by what it turns on,
 * with the description of the current state as one line of help text.
 */
export function SessionOptionSwitches({ items }: { items: SessionOptionTileItem[] }) {
  const t = useTranslations("newSessionButton");

  return (
    <div className="space-y-1">
      {items.map((item) => (
        <SwitchRow
          key={item.key}
          checked={item.active}
          label={getOptionCopy(t, item.key, true).title}
          description={getOptionCopy(t, item.key, item.active).description}
          warning={lowersSafeguard(item.key)}
          disabled={item.disabled}
          onCheckedChange={() => item.onClick?.()}
        />
      ))}
    </div>
  );
}
