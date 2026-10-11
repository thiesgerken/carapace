"use client";

import type { ReactNode } from "react";
import { useLocale } from "next-intl";
import { isoWeek, monthWeeks } from "@/lib/memory";
import { cn } from "@/lib/utils";

/** The week number column, then Monday to Sunday. */
export const calendarRowClassName = "grid grid-cols-[3.5rem_repeat(7,minmax(0,1fr))] gap-px";

/**
 * A month as rows of ISO weeks, Monday first. The rows are the weeks whose Thursday falls in the
 * month, so a boundary week shows under the month it belongs to and its other days are muted.
 */
export function MonthCalendar({ monthKey, renderRow, weekCell, dayCell }: {
  monthKey: string;
  /** Wraps a week's cells, e.g. in a link or button; `className` lays them out. */
  renderRow: (weekKey: string, cells: ReactNode, className: string) => ReactNode;
  weekCell: (weekKey: string) => ReactNode;
  dayCell?: (weekKey: string, dayIndex: number) => ReactNode;
}) {
  const locale = useLocale();
  const weekday = new Intl.DateTimeFormat(locale, { weekday: "narrow", timeZone: "UTC" });
  const dayNumber = new Intl.DateTimeFormat(locale, { day: "numeric", timeZone: "UTC" });
  // 2024-01-01 is a Monday.
  const weekdays = Array.from({ length: 7 }, (_, index) => weekday.format(Date.UTC(2024, 0, 1 + index)));
  const month = Number(monthKey.slice(5)) - 1;

  return (
    <div className="space-y-px text-sm">
      <div aria-hidden="true" className={cn(calendarRowClassName, "text-center text-xs text-muted-foreground")}>
        <span />
        {weekdays.map((name, index) => <span key={index}>{name}</span>)}
      </div>
      {monthWeeks(monthKey).map((weekKey) => {
        const { start } = isoWeek(weekKey);
        const cells = (
          <>
            <span className="flex flex-col justify-center px-1.5">{weekCell(weekKey)}</span>
            {Array.from({ length: 7 }, (_, index) => {
              const day = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth(), start.getUTCDate() + index));
              return (
                <span key={index} className={cn("flex min-h-10 flex-col items-center gap-0.5 rounded-md py-1", day.getUTCMonth() !== month && "text-muted-foreground/50")}>
                  <span className="text-xs tabular-nums">{dayNumber.format(day)}</span>
                  {dayCell?.(weekKey, index)}
                </span>
              );
            })}
          </>
        );
        return <div key={weekKey}>{renderRow(weekKey, cells, calendarRowClassName)}</div>;
      })}
    </div>
  );
}
