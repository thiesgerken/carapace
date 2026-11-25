"use client";

import Link from "next/link";
import { useCallback, useRef, useState, type ReactNode } from "react";
import { Archive, ArchiveRestore, Bug, Ellipsis, Pin, PinOff, Star, StarOff, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useDismiss } from "@/hooks/use-dismiss";
import { cn } from "@/lib/utils";

const itemClassName =
  "flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-transparent";

/** The session's actions behind a `⋯` button in the chat header. */
export function SessionMenu({
  sessionId,
  pinned,
  favorite,
  archived,
  canArchive,
  attributesDisabled,
  deleteDisabled,
  onTogglePinned,
  onToggleFavorite,
  onToggleArchived,
  onDelete,
}: {
  sessionId: string;
  pinned: boolean;
  favorite: boolean;
  archived: boolean;
  canArchive: boolean;
  attributesDisabled: boolean;
  deleteDisabled: boolean;
  onTogglePinned: () => void;
  onToggleFavorite: () => void;
  onToggleArchived: () => void;
  onDelete: () => void;
}) {
  const t = useTranslations();
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const closeMenu = useCallback(() => setOpen(false), []);
  useDismiss(menuRef, open, closeMenu);

  /** Closes the menu before the action, so a confirm dialog it opens doesn't sit on top of the open menu. */
  const select = (action: () => void) => () => {
    setOpen(false);
    action();
  };

  return (
    <div ref={menuRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t("sessionView.menu")}
        title={t("sessionView.menu")}
        className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Ellipsis className="h-4 w-4" />
      </button>
      {open ? (
        <div
          role="menu"
          aria-label={t("sessionView.menu")}
          className="absolute right-0 top-full z-50 mt-1 w-56 rounded-lg border border-border bg-background p-1 text-foreground shadow-lg"
        >
          <MenuButton icon={pinned ? <PinOff /> : <Pin />} disabled={attributesDisabled} onClick={select(onTogglePinned)}>
            {t(pinned ? "chatView.actions.unpin" : "chatView.actions.pin")}
          </MenuButton>
          <MenuButton icon={favorite ? <StarOff /> : <Star />} disabled={attributesDisabled} onClick={select(onToggleFavorite)}>
            {t(favorite ? "chatView.actions.unfavorite" : "chatView.actions.favorite")}
          </MenuButton>
          {archived || canArchive ? (
            <MenuButton icon={archived ? <ArchiveRestore /> : <Archive />} disabled={attributesDisabled} onClick={select(onToggleArchived)}>
              {t(archived ? "chatView.actions.unarchive" : "chatView.actions.archive")}
            </MenuButton>
          ) : null}
          <Link
            role="menuitem"
            href={`/?session=${encodeURIComponent(sessionId)}&view=debug`}
            onClick={closeMenu}
            className={itemClassName}
          >
            <Bug className="h-4 w-4 shrink-0 text-muted-foreground" />
            {t("sessionView.debug")}
          </Link>
          <div role="separator" className="my-1 h-px bg-border" />
          <MenuButton icon={<Trash2 />} disabled={deleteDisabled} onClick={select(onDelete)} destructive>
            {t("chatView.actions.delete")}
          </MenuButton>
        </div>
      ) : null}
    </div>
  );
}

function MenuButton({
  icon,
  disabled,
  destructive = false,
  onClick,
  children,
}: {
  icon: ReactNode;
  disabled: boolean;
  destructive?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      disabled={disabled}
      onClick={onClick}
      className={cn(itemClassName, destructive && "text-destructive hover:bg-destructive/10")}
    >
      <span className={cn("shrink-0 [&>svg]:h-4 [&>svg]:w-4", destructive ? "text-destructive" : "text-muted-foreground")}>{icon}</span>
      {children}
    </button>
  );
}
