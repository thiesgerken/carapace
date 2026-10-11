"use client";

import Link from "next/link";
import { ArrowLeft, Check, Loader2, Plus, RefreshCw, Save, ShieldCheck, Trash2, UserPlus, Users } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { createAdminUser, deleteAdminUser, getCurrentUser, listAdminUsers, updateAdminUser, type AdminUserInfo } from "@/lib/api";
import { normalizeServer } from "@/lib/server-url";
import { getServer } from "@/lib/storage";
import { cn } from "@/lib/utils";

type UserDraft = {
  displayName: string;
  email: string;
  roles: string;
  enabled: boolean;
  password: string;
};

type CreateDraft = {
  username: string;
  password: string;
  displayName: string;
  email: string;
  roles: string;
};

const emptyCreateDraft: CreateDraft = {
  username: "",
  password: "",
  displayName: "",
  email: "",
  roles: "",
};

function rolesFromText(value: string): string[] {
  return [...new Set(value.split(/[\n,]/).map((role) => role.trim()).filter(Boolean))];
}

function textFromRoles(roles: string[]): string {
  return roles.join(", ");
}

function draftFromUser(user: AdminUserInfo): UserDraft {
  return {
    displayName: user.display_name,
    email: user.email ?? "",
    roles: textFromRoles(user.roles),
    enabled: user.enabled,
    password: "",
  };
}

function formatTimestamp(value: string | null, fallback: string): string {
  if (!value) return fallback;
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

const inputClassName = cn(
  "w-full rounded-lg border border-border bg-background px-3 py-2 text-base sm:text-sm",
  "outline-none transition-colors placeholder:text-muted-foreground/50",
  "focus:border-ring focus:ring-2 focus:ring-ring/30",
);

const iconButtonClassName = cn(
  "inline-flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground transition-colors",
  "hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50",
);

interface AdminUsersPageProps {
  embedded?: boolean;
  server?: string;
  currentUsername?: string | null;
}

export function AdminUsersPage({ embedded = false, server: serverProp, currentUsername = null }: AdminUsersPageProps = {}) {
  const t = useTranslations("admin");
  const [server, setServer] = useState(() => normalizeServer(serverProp ?? ""));
  const [users, setUsers] = useState<AdminUserInfo[]>([]);
  const [selectedUsername, setSelectedUsername] = useState<string | "new">("new");
  const [editDraft, setEditDraft] = useState<UserDraft | null>(null);
  const [createDraft, setCreateDraft] = useState<CreateDraft>(emptyCreateDraft);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [creating, setCreating] = useState(false);
  const [deletingUsername, setDeletingUsername] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [resolvedCurrentUsername, setResolvedCurrentUsername] = useState<string | null>(currentUsername);
  const loadedServerRef = useRef<string | null>(null);

  const selectedUser = useMemo(
    () => users.find((user) => user.username === selectedUsername) ?? null,
    [selectedUsername, users],
  );

  useEffect(() => {
    const timer = setTimeout(() => {
      const nextServer = normalizeServer(serverProp ?? getServer());
      setServer((current) => current === nextServer ? current : nextServer);
    }, 0);

    return () => {
      clearTimeout(timer);
    };
  }, [serverProp]);

  const refreshUsers = useCallback(async (preferredUsername: string | "new" = selectedUsername, message?: string): Promise<void> => {
    const normalizedServer = normalizeServer(server);
    if (!normalizedServer) {
      setError(t("errors.missingCredentials"));
      setNotice(null);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const [loadedUsers, loadedCurrentUser] = await Promise.all([
        listAdminUsers(normalizedServer),
        currentUsername === null ? getCurrentUser(normalizedServer).catch(() => null) : Promise.resolve(null),
      ]);
      setUsers(loadedUsers);
      setResolvedCurrentUsername(currentUsername ?? loadedCurrentUser?.username ?? null);
      if (preferredUsername === "new") {
        setSelectedUsername("new");
        setEditDraft(null);
      } else if (loadedUsers.some((user) => user.username === preferredUsername)) {
        setSelectedUsername(preferredUsername);
        setEditDraft(draftFromUser(loadedUsers.find((user) => user.username === preferredUsername)!));
      } else {
        const fallbackUser = loadedUsers[0] ?? null;
        setSelectedUsername(fallbackUser?.username ?? "new");
        setEditDraft(fallbackUser === null ? null : draftFromUser(fallbackUser));
      }
      setNotice(message ?? t("notices.loaded"));
    } catch (refreshError) {
      setError(refreshError instanceof Error ? refreshError.message : t("errors.load"));
      setNotice(null);
    } finally {
      setLoading(false);
    }
  }, [currentUsername, selectedUsername, server, t]);

  useEffect(() => {
    if (!embedded) return;
    const normalizedServer = normalizeServer(server);
    if (!normalizedServer || loadedServerRef.current === normalizedServer) return;
    loadedServerRef.current = normalizedServer;
    void refreshUsers(selectedUsername);
  }, [embedded, refreshUsers, selectedUsername, server]);

  async function handleCreateUser(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const normalizedServer = normalizeServer(server);
    if (!normalizedServer) {
      setError(t("errors.missingCredentials"));
      setNotice(null);
      return;
    }

    setCreating(true);
    setError(null);
    try {
      const created = await createAdminUser(normalizedServer, {
        username: createDraft.username.trim(),
        password: createDraft.password,
        display_name: createDraft.displayName.trim(),
        email: createDraft.email.trim() || null,
        roles: rolesFromText(createDraft.roles),
      });
      setCreateDraft(emptyCreateDraft);
      await refreshUsers(created.username, t("notices.created", { username: created.username }));
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : t("errors.create"));
      setNotice(null);
    } finally {
      setCreating(false);
    }
  }

  async function handleSaveUser(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (selectedUser === null || editDraft === null) return;
    const normalizedServer = normalizeServer(server);
    if (!normalizedServer) {
      setError(t("errors.missingCredentials"));
      setNotice(null);
      return;
    }

    setSaving(true);
    setError(null);
    try {
      const updated = await updateAdminUser(normalizedServer, selectedUser.username, {
        display_name: editDraft.displayName.trim(),
        email: editDraft.email.trim() || null,
        roles: rolesFromText(editDraft.roles),
        enabled: editDraft.enabled,
        ...(editDraft.password ? { password: editDraft.password } : {}),
      });
      await refreshUsers(updated.username, t("notices.saved", { username: updated.username }));
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : t("errors.save"));
      setNotice(null);
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteUser(username: string): Promise<void> {
    const normalizedServer = normalizeServer(server);
    if (!normalizedServer) {
      setError(t("errors.missingCredentials"));
      setNotice(null);
      return;
    }
    if (username === (currentUsername ?? resolvedCurrentUsername)) {
      return;
    }
    if (!window.confirm(t("confirm.deleteUser", { username }))) {
      return;
    }

    setDeletingUsername(username);
    setError(null);
    setNotice(null);
    try {
      await deleteAdminUser(normalizedServer, username);
      await refreshUsers("new", t("notices.deleted", { username }));
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : t("errors.delete"));
      setNotice(null);
    } finally {
      setDeletingUsername(null);
    }
  }

  const selectedIsNew = selectedUsername === "new";
  const visibleCurrentUsername = currentUsername ?? resolvedCurrentUsername;
  const ContentElement = embedded ? "section" : "main";

  const mainContent = (
    <ContentElement className={cn("flex min-w-0 flex-1 flex-col overflow-clip", embedded && "bg-background/65")}>
        {!embedded ? (
          <header className="border-b border-border/80 bg-background/70 px-4 py-3 backdrop-blur sm:px-6">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground md:hidden">
                  <ShieldCheck className="h-4 w-4" />
                  {t("title")}
                </div>
                <h1 className="mt-1 text-2xl font-semibold tracking-tight md:mt-0">{t("users.title")}</h1>
                <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{t("users.description")}</p>
              </div>
              <button
                type="button"
                onClick={() => void refreshUsers()}
                disabled={loading || !server.trim()}
                className="inline-flex min-h-10 items-center justify-center gap-2 self-end rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-background transition-colors hover:bg-foreground/90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                {loading ? t("actions.loading") : t("actions.load")}
              </button>
            </div>
            {(error || notice) && (
              <div className={cn("mt-3 text-sm", error ? "text-destructive" : "text-muted-foreground")}>
                {error ?? notice}
              </div>
            )}
          </header>
        ) : null}

        <div className="grid min-h-0 flex-1 lg:grid-cols-[22rem_minmax(0,1fr)]">
          <section className="min-h-0 border-b border-border/80 bg-background/55 lg:border-r lg:border-b-0">
            <div className="flex items-center justify-between gap-3 border-b border-border/70 px-4 py-3 sm:px-5">
              <div className="text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">
                {t("users.savedUsers")}
              </div>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => void refreshUsers(selectedUsername, t("notices.loaded"))}
                  title={t("actions.refresh")}
                  aria-label={t("actions.refresh")}
                  className={iconButtonClassName}
                  disabled={loading || !server.trim()}
                >
                  <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setSelectedUsername("new");
                    setEditDraft(null);
                    setError(null);
                    setNotice(null);
                  }}
                  title={t("actions.new")}
                  aria-label={t("actions.new")}
                  className={iconButtonClassName}
                >
                  <Plus className="h-4 w-4" />
                </button>
              </div>
            </div>
            <div className="max-h-72 min-h-0 overflow-y-auto p-3 lg:max-h-none lg:h-full">
              {loading ? (
                <div className="flex items-center gap-2 rounded-lg border border-dashed border-border px-4 py-5 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t("users.loading")}
                </div>
              ) : users.length === 0 ? (
                <div className="rounded-lg border border-dashed border-border bg-background/80 px-4 py-6 text-sm text-muted-foreground">
                  {t("users.empty")}
                </div>
              ) : (
                <div className="space-y-2">
                  {users.map((user) => {
                    const selected = selectedUsername === user.username;
                    const isCurrentUser = user.username === visibleCurrentUsername;
                    const deleting = deletingUsername === user.username;
                    const isAdminUser = user.roles.some((role) => role.trim().toLowerCase() === "admin");
                    return (
                      <div key={user.username} className="flex items-stretch gap-1">
                        <button
                          type="button"
                          onClick={() => {
                            setSelectedUsername(user.username);
                            setEditDraft(draftFromUser(user));
                            setError(null);
                            setNotice(null);
                          }}
                          className={cn(
                            "min-w-0 flex-1 rounded-lg px-3 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                            selected ? "bg-accent text-accent-foreground" : "text-foreground/80 hover:bg-muted",
                          )}
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <div className="flex min-w-0 items-center gap-2">
                                <span className="truncate text-sm font-semibold">{user.display_name || user.username}</span>
                                {isCurrentUser ? (
                                  <span className={cn(
                                    "shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium",
                                    selected ? "bg-accent-foreground/15 text-accent-foreground" : "bg-muted text-muted-foreground",
                                  )}>
                                    {t("users.you")}
                                  </span>
                                ) : null}
                              </div>
                              <div className={cn("mt-0.5 truncate font-mono text-xs", selected ? "text-accent-foreground/70" : "text-foreground/70")}>
                                {user.username}
                              </div>
                            </div>
                            <div className="flex shrink-0 flex-wrap justify-end gap-1">
                              <span className={cn(
                                "rounded-full px-2 py-0.5 text-[11px] font-medium",
                                user.enabled ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700",
                              )}>
                                {user.enabled ? t("users.enabled") : t("users.disabled")}
                              </span>
                              {isAdminUser ? (
                                <span className={cn(
                                  "rounded-full px-2 py-0.5 text-[11px] font-medium",
                                  selected ? "bg-accent-foreground/15 text-accent-foreground" : "bg-accent text-accent-foreground",
                                )}>
                                  {t("users.admin")}
                                </span>
                              ) : null}
                            </div>
                          </div>
                        </button>
                        {!isCurrentUser ? (
                          <button
                            type="button"
                            onClick={() => void handleDeleteUser(user.username)}
                            title={t("actions.deleteUser", { username: user.username })}
                            aria-label={t("actions.deleteUser", { username: user.username })}
                            className={cn(iconButtonClassName, "hover:bg-destructive/10 hover:text-destructive")}
                            disabled={deletingUsername !== null || loading || !server.trim()}
                          >
                            {deleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                          </button>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </section>

          <section className="min-h-0 overflow-y-auto px-4 py-5 sm:px-6">
            {embedded && error ? (
              <div className="mx-auto mb-4 max-w-3xl rounded-2xl border border-border bg-background/88 px-4 py-3 text-sm shadow-sm">
                <p className="text-destructive">{error}</p>
              </div>
            ) : null}
            {selectedIsNew ? (
              <form onSubmit={(event) => void handleCreateUser(event)} className="mx-auto max-w-3xl space-y-5">
                <div className="flex items-center gap-3">
                  <div className="rounded-lg border border-border bg-background p-2 text-muted-foreground">
                    <UserPlus className="h-4 w-4" />
                  </div>
                  <div>
                    <h2 className="text-lg font-semibold tracking-tight">{t("create.title")}</h2>
                    <p className="text-sm text-muted-foreground">{t("create.subtitle")}</p>
                  </div>
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label={t("fields.username")}>
                    <input
                      value={createDraft.username}
                      onChange={(event) => setCreateDraft((draft) => ({ ...draft, username: event.target.value }))}
                      className={inputClassName}
                      required
                    />
                  </Field>
                  <Field label={t("fields.password")}>
                    <input
                      type="password"
                      name="admin-create-user-secret"
                      autoComplete="new-password"
                      data-1p-ignore="true"
                      data-bwignore="true"
                      data-lpignore="true"
                      value={createDraft.password}
                      onChange={(event) => setCreateDraft((draft) => ({ ...draft, password: event.target.value }))}
                      className={inputClassName}
                      required
                    />
                  </Field>
                  <Field label={t("fields.displayName")}>
                    <input
                      value={createDraft.displayName}
                      onChange={(event) => setCreateDraft((draft) => ({ ...draft, displayName: event.target.value }))}
                      className={inputClassName}
                    />
                  </Field>
                  <Field label={t("fields.email")}>
                    <input
                      type="email"
                      value={createDraft.email}
                      onChange={(event) => setCreateDraft((draft) => ({ ...draft, email: event.target.value }))}
                      className={inputClassName}
                    />
                  </Field>
                  <Field label={t("fields.roles")} className="sm:col-span-2">
                    <input
                      value={createDraft.roles}
                      onChange={(event) => setCreateDraft((draft) => ({ ...draft, roles: event.target.value }))}
                      placeholder="admin, matrix"
                      className={inputClassName}
                    />
                  </Field>
                </div>

                <button
                  type="submit"
                  disabled={creating || !createDraft.username.trim() || !createDraft.password || !server.trim()}
                  className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-background transition-colors hover:bg-foreground/90 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4" />}
                  {creating ? t("actions.creating") : t("actions.create")}
                </button>
              </form>
            ) : selectedUser && editDraft ? (
              <form onSubmit={(event) => void handleSaveUser(event)} className="mx-auto max-w-3xl space-y-5">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <div className="font-mono text-xs text-muted-foreground">{selectedUser.username}</div>
                    <h2 className="mt-1 text-2xl font-semibold tracking-tight">{selectedUser.display_name || selectedUser.username}</h2>
                    <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
                      <span>{t("meta.tokenVersion", { version: selectedUser.token_version })}</span>
                      <span>{t("meta.updated", { timestamp: formatTimestamp(selectedUser.updated_at, t("meta.never")) })}</span>
                      <span>{t("meta.lastLogin", { timestamp: formatTimestamp(selectedUser.last_login_at, t("meta.never")) })}</span>
                    </div>
                  </div>
                  <label className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2 text-sm font-medium">
                    <input
                      type="checkbox"
                      checked={editDraft.enabled}
                      onChange={(event) => setEditDraft((draft) => draft ? { ...draft, enabled: event.target.checked } : draft)}
                      className="h-4 w-4 rounded border-border accent-foreground"
                    />
                    {t("fields.enabled")}
                  </label>
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label={t("fields.displayName")}>
                    <input
                      value={editDraft.displayName}
                      onChange={(event) => setEditDraft((draft) => draft ? { ...draft, displayName: event.target.value } : draft)}
                      className={inputClassName}
                    />
                  </Field>
                  <Field label={t("fields.email")}>
                    <input
                      type="email"
                      value={editDraft.email}
                      onChange={(event) => setEditDraft((draft) => draft ? { ...draft, email: event.target.value } : draft)}
                      className={inputClassName}
                    />
                  </Field>
                  <Field label={t("fields.roles")}>
                    <input
                      value={editDraft.roles}
                      onChange={(event) => setEditDraft((draft) => draft ? { ...draft, roles: event.target.value } : draft)}
                      placeholder="admin, matrix"
                      className={inputClassName}
                    />
                  </Field>
                  <Field label={t("fields.newPassword")}>
                    <input
                      type="password"
                      name="admin-edit-user-secret"
                      autoComplete="new-password"
                      data-1p-ignore="true"
                      data-bwignore="true"
                      data-lpignore="true"
                      value={editDraft.password}
                      onChange={(event) => setEditDraft((draft) => draft ? { ...draft, password: event.target.value } : draft)}
                      placeholder={t("fields.keepPassword")}
                      className={inputClassName}
                    />
                  </Field>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="submit"
                    disabled={saving || !server.trim()}
                    className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-background transition-colors hover:bg-foreground/90 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                    {saving ? t("actions.saving") : t("actions.save")}
                  </button>
                  {notice && !error && (
                    <span className="inline-flex items-center gap-1 text-sm text-muted-foreground">
                      <Check className="h-4 w-4" />
                      {notice}
                    </span>
                  )}
                </div>
              </form>
            ) : (
              <div className="mx-auto max-w-3xl rounded-lg border border-dashed border-border bg-background/75 px-4 py-6 text-sm text-muted-foreground">
                {t("users.selectUser")}
              </div>
            )}
          </section>
        </div>
        </ContentElement>
  );

  if (embedded) {
    return mainContent;
  }

  return (
    <div className="flex h-dvh overflow-clip bg-[radial-gradient(circle_at_top_left,_color-mix(in_oklch,var(--accent)_55%,transparent),transparent_35%),linear-gradient(180deg,color-mix(in_oklch,var(--background)_96%,var(--muted))_0%,var(--background)_100%)]">
      <aside className="hidden w-72 shrink-0 border-r border-border bg-background/88 md:flex md:flex-col">
        <div className="border-b border-border px-5 py-4">
          <div className="flex items-center gap-2 text-sm font-semibold tracking-tight">
            <ShieldCheck className="h-4 w-4 text-muted-foreground" />
            {t("title")}
          </div>
        </div>
        <nav className="flex-1 p-3">
          <button
            type="button"
            className="flex w-full items-center gap-2 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-accent-foreground"
          >
            <Users className="h-4 w-4" />
            {t("users.title")}
          </button>
        </nav>
        <div className="border-t border-border p-3">
          <Link
            href="/"
            className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4" />
            {t("backToApp")}
          </Link>
        </div>
      </aside>

      {mainContent}
    </div>
  );
}

function Field({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <label className={cn("space-y-1.5", className)}>
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}
