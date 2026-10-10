import { useTranslations } from "next-intl";
import { AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";

interface VersionBadgeProps {
  frontendVersion?: string | null;
  backendVersion?: string | null;
  className?: string;
  textClassName?: string;
  iconClassName?: string;
}

function normalizeVersion(value: string | null | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
}

export function VersionBadge({
  frontendVersion,
  backendVersion,
  className,
  textClassName,
  iconClassName,
}: VersionBadgeProps) {
  const t = useTranslations("versionBadge");
  const normalizedFrontendVersion = normalizeVersion(frontendVersion);
  const normalizedBackendVersion = normalizeVersion(backendVersion);
  const visibleVersion = normalizedBackendVersion || normalizedFrontendVersion;

  if (!visibleVersion) {
    return null;
  }

  const hasMismatch = !!normalizedFrontendVersion
    && !!normalizedBackendVersion
    && normalizedFrontendVersion !== normalizedBackendVersion;

  const tooltip = [
    t("frontend", { version: normalizedFrontendVersion ?? t("unknown") }),
    t("backend", { version: normalizedBackendVersion ?? t("unknown") }),
    ...(hasMismatch ? ["", t("mismatchTooltip")] : []),
  ].join("\n");

  // Shrinks with the row and shows the version only if it fits whole. The zero-width,
  // full-height spacer opens the first flex line, so a version too wide for the slot wraps onto
  // the second line, which the fixed height clips away. No truncation into neighbouring text.
  // The mismatch warning sits outside the clip: a stale frontend must stay visible.
  return (
    <span
      title={tooltip}
      className={cn("flex min-w-0 cursor-help items-center gap-1 text-xs font-medium text-muted-foreground", className)}
    >
      <span className="flex h-4 min-w-0 flex-wrap overflow-hidden">
        <span aria-hidden="true" className="h-4 w-0" />
        <span className={cn("h-4 leading-4", textClassName)}>v{visibleVersion}</span>
      </span>
      {hasMismatch ? (
        <span className="flex shrink-0 items-center">
          <AlertTriangle className={cn("h-3.5 w-3.5 text-amber-600", iconClassName)} />
          <span className="sr-only">{t("mismatchSr")}</span>
        </span>
      ) : null}
    </span>
  );
}
