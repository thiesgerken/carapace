"use client";

import { CircleAlert, TriangleAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import type { SandboxUsage } from "@/lib/types";
import { cn } from "@/lib/utils";

const bannerClassName = "flex items-start gap-2 rounded-lg px-3 py-2 text-xs leading-snug";

export function SandboxUsageBanner({ usage }: { usage: SandboxUsage | null }) {
  const t = useTranslations("sidebar.sandboxUsage");
  if (!usage) return null;

  const { count, warn_at: warnAt, max } = usage;
  if (max > 0 && count >= max) {
    return (
      <div role="alert" className={cn(bannerClassName, "bg-destructive/10 text-destructive")}>
        <CircleAlert className="mt-px h-3.5 w-3.5 shrink-0" />
        <span>{t("limitReached", { count, max })}</span>
      </div>
    );
  }
  if (warnAt > 0 && count >= warnAt) {
    return (
      <div role="status" title={t("warnAt", { warnAt })} className={cn(bannerClassName, "bg-warning/10 text-warning")}>
        <TriangleAlert className="mt-px h-3.5 w-3.5 shrink-0" />
        <span>
          {max > 0 ? t("warning", { count, max }) : t("warningUnlimited", { count })}
        </span>
      </div>
    );
  }
  return null;
}
