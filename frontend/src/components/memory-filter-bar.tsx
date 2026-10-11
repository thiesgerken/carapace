"use client";

import { useId, useRef, useState, type ReactNode } from "react";
import { CalendarDays, ChevronDown, ChevronLeft, ChevronRight, FunnelX, Search, X, type LucideIcon } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { MonthCalendar } from "@/components/month-calendar";
import { monthLabel, periodLevel, periodMonth, weekLabel } from "@/lib/memory";
import { cn } from "@/lib/utils";

const controlClassName = "h-9 rounded-lg border bg-background text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30";
/** A filter changed from its tab's default stands out, so a narrowed list never passes for the default one. */
function stateClassName(active: boolean): string {
  return active ? "border-[#236b86]/60 bg-[#236b86]/10 dark:border-sky-400/50 dark:bg-sky-400/10" : "border-border";
}
const iconClassName = "pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground";

/** Shallow, which is all a filter form needs. */
export function differsFrom<T extends object>(form: T, defaults: T): boolean {
  return (Object.keys(defaults) as (keyof T)[]).some((key) => form[key] !== defaults[key]);
}

/** Filters on the left, then reset (only while something differs from the defaults), the count and the actions. */
export function FilterBar({ count, canReset, onReset, actions, children }: {
  count: ReactNode;
  canReset: boolean;
  onReset: () => void;
  actions?: ReactNode;
  children: ReactNode;
}) {
  const t = useTranslations("memory.filterBar");
  return (
    <div className="flex flex-wrap items-center gap-2">
      {children}
      {canReset ? (
        <button type="button" onClick={onReset} className="inline-flex h-9 items-center gap-1.5 rounded-lg px-2.5 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground">
          <FunnelX aria-hidden="true" className="h-4 w-4" />
          {t("reset")}
        </button>
      ) : null}
      <div className="ml-auto flex items-center gap-3">
        <span className="text-sm tabular-nums text-muted-foreground">{count}</span>
        {actions}
      </div>
    </div>
  );
}

export function FilterSelect<T extends string>({ icon: Icon, label, anyLabel, value, active, options, onChange }: {
  icon: LucideIcon;
  label: string;
  anyLabel: string;
  value: T | "";
  /** Differs from the tab's default; see FilterBar. */
  active: boolean;
  options: readonly { value: T; label: string }[];
  onChange: (value: T | "") => void;
}) {
  return (
    <span className="relative inline-flex">
      <Icon aria-hidden="true" className={iconClassName} />
      <select
        aria-label={label}
        title={label}
        value={value}
        onChange={(event) => onChange(event.target.value as T | "")}
        data-active={active || undefined}
        className={cn(controlClassName, stateClassName(active), "appearance-none pl-8 pr-8")}
      >
        <option value="">{anyLabel}</option>
        {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
      <ChevronDown aria-hidden="true" className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
    </span>
  );
}

export function FilterSearch({ label, value, active, onChange }: { label: string; value: string; active: boolean; onChange: (value: string) => void }) {
  return (
    <span className="relative inline-flex min-w-40 flex-1">
      <Search aria-hidden="true" className={iconClassName} />
      <input
        type="search"
        aria-label={label}
        placeholder={label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        data-active={active || undefined}
        className={cn(controlClassName, stateClassName(active), "w-full pl-8 pr-2.5")}
      />
    </span>
  );
}

function shiftMonth(key: string, delta: number): string {
  const [year, month] = key.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1 + delta, 1)).toISOString().slice(0, 7);
}

const PANEL_WIDTH = 288;

/**
 * A week (and with `allowMonth` also a month) picked from a month calendar in a native popover,
 * which brings light dismiss, Escape and the top layer. `<input type="week">` is Chromium-only.
 */
export function PeriodPicker({ label, value, active, allowMonth, onChange }: {
  label: string;
  /** A week key, a month key when `allowMonth`, or "" for none. */
  value: string;
  active: boolean;
  allowMonth: boolean;
  onChange: (value: string) => void;
}) {
  const t = useTranslations("memory.filterBar");
  const locale = useLocale();
  const panelId = useId();
  const panel = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(() => (value ? periodMonth(value) : new Date().toISOString().slice(0, 7)));
  const [position, setPosition] = useState({ top: 0, left: 0 });

  function pick(key: string): void {
    onChange(key);
    panel.current?.hidePopover();
  }

  const text = value === ""
    ? label
    : periodLevel(value) === "week" ? `${value.slice(5)} · ${weekLabel(value, locale, false)}` : monthLabel(value, locale, true);

  return (
    <span className="relative inline-flex">
      <CalendarDays aria-hidden="true" className={iconClassName} />
      <button
        type="button"
        popoverTarget={panelId}
        aria-label={label}
        title={value && periodLevel(value) === "week" ? weekLabel(value, locale, true) : label}
        onClick={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          setPosition({ top: rect.bottom + 4, left: Math.max(8, Math.min(rect.left, window.innerWidth - PANEL_WIDTH - 8)) });
          if (value) setShown(periodMonth(value));
        }}
        data-active={active || undefined}
        className={cn(controlClassName, stateClassName(active), "whitespace-nowrap pl-8 text-left", value ? "pr-8" : "pr-2.5 text-muted-foreground")}
      >
        {text}
      </button>
      {value ? (
        <button
          type="button"
          onClick={() => onChange("")}
          aria-label={t("clear")}
          title={t("clear")}
          className="absolute right-1.5 top-1/2 inline-flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      ) : null}
      <div
        ref={panel}
        id={panelId}
        popover="auto"
        style={{ inset: "auto", top: position.top, left: position.left, width: PANEL_WIDTH }}
        className="m-0 space-y-2 rounded-lg border border-border bg-background p-2 text-foreground shadow-lg"
      >
        <div className="flex items-center gap-1">
          <button type="button" onClick={() => setShown(shiftMonth(shown, -1))} aria-label={t("previousMonth")} className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground">
            <ChevronLeft className="h-4 w-4" />
          </button>
          {allowMonth ? (
            <button
              type="button"
              onClick={() => pick(shown)}
              title={t("wholeMonth")}
              className={cn("h-8 flex-1 rounded-md text-sm font-semibold hover:bg-muted", value === shown && "bg-accent text-accent-foreground")}
            >
              {monthLabel(shown, locale, true)}
            </button>
          ) : (
            <span className="flex-1 text-center text-sm font-semibold">{monthLabel(shown, locale, true)}</span>
          )}
          <button type="button" onClick={() => setShown(shiftMonth(shown, 1))} aria-label={t("nextMonth")} className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground">
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
        <MonthCalendar
          monthKey={shown}
          renderRow={(weekKey, cells, className) => (
            <button type="button" onClick={() => pick(weekKey)} className={cn(className, "w-full rounded-md text-left hover:bg-muted", weekKey === value && "bg-accent text-accent-foreground")}>
              {cells}
            </button>
          )}
          weekCell={(weekKey) => <span className="text-xs font-medium">{weekKey.slice(5)}</span>}
        />
      </div>
    </span>
  );
}
