"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useRef, useState } from "react";
import { BookOpen, Brain, LogOut, Settings2, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { GlobalGitIndicator, useGlobalGit } from "@/components/git-sync";
import { VersionBadge, versionMismatch } from "@/components/version-badge";
import { useDismiss } from "@/hooks/use-dismiss";
import type { AuthUserInfo } from "@/lib/api";
import { cn } from "@/lib/utils";

const NAV_ITEMS: { href: string; labelKey: "knowledge" | "memory" | "settings"; icon: LucideIcon }[] = [
  { href: "/knowledge", labelKey: "knowledge", icon: BookOpen },
  { href: "/memory", labelKey: "memory", icon: Brain },
  { href: "/settings", labelKey: "settings", icon: Settings2 },
];

const menuItemClassName = "flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm text-foreground transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function accountInitial(user: AuthUserInfo | null | undefined): string {
  const label = user?.display_name?.trim() || user?.username.trim() || "?";
  return label.slice(0, 1).toLocaleUpperCase();
}

function GitHubIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      className={className}
      fill="currentColor"
    >
      <path d="M12 1.5C6.201 1.5 1.5 6.201 1.5 12c0 4.64 3.01 8.577 7.184 9.966.525.097.716-.228.716-.507 0-.25-.009-.913-.015-1.792-2.922.635-3.538-1.409-3.538-1.409-.478-1.213-1.168-1.536-1.168-1.536-.955-.652.072-.639.072-.639 1.056.074 1.611 1.084 1.611 1.084.939 1.608 2.463 1.144 3.063.875.095-.68.368-1.144.668-1.407-2.333-.265-4.785-1.166-4.785-5.192 0-1.147.41-2.085 1.082-2.82-.108-.266-.469-1.336.102-2.786 0 0 .882-.282 2.89 1.077A10.048 10.048 0 0 1 12 6.59c.892.004 1.79.121 2.629.355 2.006-1.359 2.887-1.077 2.887-1.077.573 1.45.212 2.52.104 2.786.674.735 1.08 1.673 1.08 2.82 0 4.036-2.456 4.924-4.797 5.184.378.325.714.965.714 1.946 0 1.406-.013 2.54-.013 2.886 0 .282.189.609.723.506A10.503 10.503 0 0 0 22.5 12c0-5.799-4.701-10.5-10.5-10.5Z" />
    </svg>
  );
}
function isActiveRoute(pathname: string | null, href: string): boolean {
  return pathname === href || (pathname?.startsWith(`${href}/`) ?? false);
}

/** The bottom of the sidebar: labelled app navigation, then the account row with its menu. */
export function SidebarFooter({
  server,
  token,
  currentUser,
  frontendVersion,
  backendVersion,
  githubUrl,
  onNavigate,
  onDisconnect,
}: {
  server: string;
  token: string;
  currentUser: AuthUserInfo | null;
  frontendVersion: string | null;
  backendVersion: string | null;
  githubUrl: string;
  onNavigate: () => void;
  onDisconnect: () => void;
}) {
  const t = useTranslations();
  const pathname = usePathname();
  const globalGit = useGlobalGit(server, token);

  return (
    // Below md the drawer is fixed to the viewport, so the body's safe-area padding does not reach it.
    <div className="border-t border-border px-3 pt-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] md:pb-2">
      <nav aria-label={t("navigation.label")} className="space-y-0.5">
        {NAV_ITEMS.map(({ href, labelKey, icon: Icon }) => {
          const active = isActiveRoute(pathname, href);
          return (
            <Link
              key={href}
              href={href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                active ? "bg-primary/10 text-foreground" : "text-foreground/80 hover:bg-muted",
              )}
            >
              <Icon className={cn("h-4 w-4 shrink-0", active ? "text-primary" : "text-muted-foreground")} />
              <span className="flex-1">{t(`navigation.${labelKey}`)}</span>
              {href === "/knowledge" ? <GlobalGitIndicator git={globalGit} /> : null}
            </Link>
          );
        })}
      </nav>
      <AccountMenu
        currentUser={currentUser}
        frontendVersion={frontendVersion}
        backendVersion={backendVersion}
        githubUrl={githubUrl}
        onDisconnect={onDisconnect}
      />
    </div>
  );
}

function AccountMenu({
  currentUser,
  frontendVersion,
  backendVersion,
  githubUrl,
  onDisconnect,
}: {
  currentUser: AuthUserInfo | null;
  frontendVersion: string | null;
  backendVersion: string | null;
  githubUrl: string;
  onDisconnect: () => void;
}) {
  const t = useTranslations();
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const closeMenu = useCallback(() => setOpen(false), []);
  const accountName = currentUser?.display_name?.trim() || currentUser?.username || t("account.unknown");

  useDismiss(menuRef, open, closeMenu);

  return (
    <div ref={menuRef} className="relative mt-2 border-t border-border pt-2">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        title={t("account.openMenu")}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left text-sm transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent text-[11px] font-semibold text-accent-foreground">
          {accountInitial(currentUser)}
        </span>
        <span className="min-w-0 flex-1 truncate font-medium">{accountName}</span>
        {/* A stale frontend must stay visible without opening the menu. */}
        {versionMismatch(frontendVersion, backendVersion) ? (
          <VersionBadge frontendVersion={frontendVersion} backendVersion={backendVersion} textClassName="sr-only" />
        ) : null}
      </button>

      {open ? (
        <div
          role="menu"
          aria-label={t("account.menu")}
          className="absolute inset-x-0 bottom-full z-50 mb-1 rounded-lg border border-border bg-background p-1 text-foreground shadow-lg"
        >
          <a
            role="menuitem"
            href={githubUrl}
            target="_blank"
            rel="noreferrer"
            onClick={() => setOpen(false)}
            className={menuItemClassName}
          >
            <GitHubIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
            <span className="min-w-0 flex-1 truncate">{t("navigation.github")}</span>
            <VersionBadge frontendVersion={frontendVersion} backendVersion={backendVersion} className="shrink-0" />
          </a>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onDisconnect();
            }}
            className={menuItemClassName}
          >
            <LogOut className="h-4 w-4 shrink-0 text-muted-foreground" />
            {t("account.logout")}
          </button>
        </div>
      ) : null}
    </div>
  );
}
