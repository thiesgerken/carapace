"use client";

import Link from "next/link";
import { useCallback, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { Archive, ArchiveRestore, Bug, Copy, Ellipsis, Loader2, Pin, PinOff, Star, StarOff, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useDismiss } from "@/hooks/use-dismiss";
import { cn } from "@/lib/utils";

const itemClassName =
  "flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-transparent";

type SessionAttributeActions = {
  pinned: boolean;
  favorite: boolean;
  archived: boolean;
  canArchive: boolean;
  attributesDisabled: boolean;
  onTogglePinned: () => void;
  onToggleFavorite: () => void;
  onToggleArchived: () => void;
};

/** The session's actions behind a `⋯` button in the chat header. */
export function SessionMenu({
  sessionId,
  deleteDisabled,
  busy,
  onDelete,
  ...attributeActions
}: SessionAttributeActions & {
  sessionId: string;
  deleteDisabled: boolean;
  /** An action from the menu is still running; the menu itself is closed by then. */
  busy: boolean;
  onDelete: () => void;
}) {
  const t = useTranslations();

  const copySessionId = () => {
    // Clipboard access can be denied; there is nothing useful to show for that in a closing menu.
    navigator.clipboard?.writeText(sessionId).catch(() => {});
  };

  return (
    <ActionMenu icon={busy ? <Loader2 className="animate-spin" /> : <Ellipsis />} triggerClassName="h-9 w-9 rounded-lg">
      <SessionAttributeItems {...attributeActions} />
      <Link role="menuitem" href={`/?session=${encodeURIComponent(sessionId)}&view=debug`} className={itemClassName}>
        <Bug className="h-4 w-4 shrink-0 text-muted-foreground" />
        {t("sessionView.debug")}
      </Link>
      {/* The header shows the id only from sm up, so this is the way to get at it on a phone. */}
      <MenuButton icon={<Copy />} disabled={false} onClick={copySessionId}>
        {t("sessionView.copyId")}
      </MenuButton>
      <MenuSeparator />
      <MenuButton icon={<Trash2 />} disabled={deleteDisabled} onClick={onDelete} destructive>
        {t("chatView.actions.delete")}
      </MenuButton>
    </ActionMenu>
  );
}

/** The same actions behind a `⋯` button on a sidebar row; *className* places and reveals the button. */
export function SessionRowMenu({
  className,
  onDelete,
  ...attributeActions
}: SessionAttributeActions & {
  className: string;
  /** Gets the click, so Shift can skip the confirmation. */
  onDelete: (event: MouseEvent<HTMLButtonElement>) => void;
}) {
  const t = useTranslations();
  return (
    <ActionMenu icon={<Ellipsis />} className={className} triggerClassName="h-7 w-7 rounded-md">
      <SessionAttributeItems {...attributeActions} />
      <MenuSeparator />
      <MenuButton icon={<Trash2 />} disabled={false} onClick={onDelete} destructive>
        {t("chatView.actions.delete")}
      </MenuButton>
    </ActionMenu>
  );
}

/**
 * A `⋯` button with a popover of `menuitem` children; picking one closes it. Clicks stay inside, so the menu can sit
 * in a clickable row without also triggering it. The root carries `data-open` while the menu is open.
 */
function ActionMenu({
  icon,
  className,
  triggerClassName,
  children,
}: {
  icon: ReactNode;
  className?: string;
  triggerClassName: string;
  children: ReactNode;
}) {
  const t = useTranslations();
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const closeMenu = useCallback(() => setOpen(false), []);
  useDismiss(menuRef, open, closeMenu);

  const closeOnItemClick = (event: MouseEvent<HTMLDivElement>) => {
    if (event.target instanceof Element && event.target.closest('[role="menuitem"]')) closeMenu();
  };

  return (
    <div
      ref={menuRef}
      data-open={open || undefined}
      onClick={(event) => event.stopPropagation()}
      className={cn("relative", className)}
    >
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t("sessionView.menu")}
        title={t("sessionView.menu")}
        className={cn(
          "inline-flex items-center justify-center text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&>svg]:h-4 [&>svg]:w-4",
          triggerClassName,
        )}
      >
        {icon}
      </button>
      {open ? (
        <div
          role="menu"
          aria-label={t("sessionView.menu")}
          onClick={closeOnItemClick}
          className="absolute right-0 top-full z-50 mt-1 w-56 rounded-lg border border-border bg-background p-1 text-foreground shadow-lg"
        >
          {children}
        </div>
      ) : null}
    </div>
  );
}

function SessionAttributeItems({
  pinned,
  favorite,
  archived,
  canArchive,
  attributesDisabled,
  onTogglePinned,
  onToggleFavorite,
  onToggleArchived,
}: SessionAttributeActions) {
  const t = useTranslations("chatView.actions");
  return (
    <>
      <MenuButton icon={pinned ? <PinOff /> : <Pin />} disabled={attributesDisabled} onClick={onTogglePinned}>
        {t(pinned ? "unpin" : "pin")}
      </MenuButton>
      <MenuButton icon={favorite ? <StarOff /> : <Star />} disabled={attributesDisabled} onClick={onToggleFavorite}>
        {t(favorite ? "unfavorite" : "favorite")}
      </MenuButton>
      {archived || canArchive ? (
        <MenuButton icon={archived ? <ArchiveRestore /> : <Archive />} disabled={attributesDisabled} onClick={onToggleArchived}>
          {t(archived ? "unarchive" : "archive")}
        </MenuButton>
      ) : null}
    </>
  );
}

function MenuSeparator() {
  return <div role="separator" className="my-1 h-px bg-border" />;
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
  onClick: (event: MouseEvent<HTMLButtonElement>) => void;
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
