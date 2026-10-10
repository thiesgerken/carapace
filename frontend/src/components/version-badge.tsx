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

  // Takes the row's leftover space and shows the badge only if it fits whole. The zero-width,
  // full-height spacer opens the first flex line, so a badge too wide for the slot wraps onto the
  // second line, which the fixed height clips away. No truncation into neighbouring text.
  return (
    <span className="flex h-4 min-w-0 flex-1 flex-wrap overflow-hidden">
      <span aria-hidden="true" className="h-4 w-0" />
      <span
        title={tooltip}
        className={cn("inline-flex h-4 cursor-help items-center gap-1 text-xs font-medium text-muted-foreground", className)}
      >
        <span className={textClassName}>v{visibleVersion}</span>
        {hasMismatch ? (
          <>
            <AlertTriangle className={cn("h-3.5 w-3.5 text-amber-600", iconClassName)} />
            <span className="sr-only">{t("mismatchSr")}</span>
          </>
        ) : null}
      </span>
    </span>
  );
}
