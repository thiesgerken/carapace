"use client";

import { Check, Copy, KeyRound, Loader2, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { createApiKey, listApiKeys, revokeApiKey, type ApiKeyInfo } from "@/lib/api";
import { normalizeServer } from "@/lib/server-url";
import { getServer } from "@/lib/storage";
import { cn } from "@/lib/utils";

type Access = "none" | "read" | "write";

const BASE_SCOPES = ["sessions", "jobs", "preferences", "notifications", "history", "knowledge"] as const;

const inputClassName = cn(
  "w-full rounded-lg border border-border bg-background px-3 py-2 text-base sm:text-sm",
  "outline-none transition-colors placeholder:text-muted-foreground/50",
  "focus:border-ring focus:ring-2 focus:ring-ring/30",
);

const iconButtonClassName = cn(
  "inline-flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground transition-colors",
  "hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50",
);

function formatTimestamp(value: string | null, fallback: string): string {
  if (!value) return fallback;
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return value;
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(parsed);
}

interface ApiKeysViewProps {
  server: string;
  token: string;
  isAdmin: boolean;
}

export function ApiKeysView({ server: serverProp, token, isAdmin }: ApiKeysViewProps) {
  void token;
  const t = useTranslations("apiKeys");
  const [server, setServer] = useState(() => normalizeServer(serverProp ?? ""));
  const [keys, setKeys] = useState<ApiKeyInfo[]>([]);
  const [loadedAtMs, setLoadedAtMs] = useState(0);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [grants, setGrants] = useState<Record<string, Access>>({});
  const [expiresInDays, setExpiresInDays] = useState("");
  const [createdSecret, setCreatedSecret] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const loadedServerRef = useRef<string | null>(null);

  const scopes = isAdmin ? [...BASE_SCOPES, "admin"] : [...BASE_SCOPES];

  useEffect(() => {
    const timer = setTimeout(() => {
      const nextServer = normalizeServer(serverProp ?? getServer());
      setServer((current) => (current === nextServer ? current : nextServer));
    }, 0);
    return () => clearTimeout(timer);
  }, [serverProp]);

  const refresh = useCallback(async (): Promise<void> => {
    const normalizedServer = normalizeServer(server);
    if (!normalizedServer) return;
    setLoading(true);
    setError(null);
    try {
      setKeys(await listApiKeys(normalizedServer));
      setLoadedAtMs(Date.now());
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : t("errors.load"));
    } finally {
      setLoading(false);
    }
  }, [server, t]);

  useEffect(() => {
    const normalizedServer = normalizeServer(server);
    if (!normalizedServer || loadedServerRef.current === normalizedServer) return;
    loadedServerRef.current = normalizedServer;
    void refresh();
  }, [refresh, server]);

  function setAccess(scope: string, access: Access): void {
    setGrants((current) => ({ ...current, [scope]: access }));
  }

  function selectedScopeStrings(): string[] {
    return Object.entries(grants)
      .filter(([, access]) => access !== "none")
      .map(([scope, access]) => `${scope}:${access}`);
  }

  async function handleCreate(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const normalizedServer = normalizeServer(server);
    if (!normalizedServer) return;
    const selected = selectedScopeStrings();
    if (selected.length === 0) {
      setError(t("errors.noScopes"));
      return;
    }
    setCreating(true);
    setError(null);
    try {
      const parsedDays = expiresInDays.trim() ? Number.parseInt(expiresInDays, 10) : null;
      const result = await createApiKey(normalizedServer, {
        name: name.trim(),
        scopes: selected,
        expires_in_days: parsedDays && parsedDays > 0 ? parsedDays : null,
      });
      setCreatedSecret(result.secret);
      setCopied(false);
      setName("");
      setGrants({});
      setExpiresInDays("");
      await refresh();
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : t("errors.create"));
    } finally {
      setCreating(false);
    }
  }

  async function handleRevoke(key: ApiKeyInfo): Promise<void> {
    const normalizedServer = normalizeServer(server);
    if (!normalizedServer) return;
    if (!window.confirm(t("confirm.revoke", { name: key.name || key.prefix }))) return;
    setRevokingId(key.id);
    setError(null);
    try {
      await revokeApiKey(normalizedServer, key.id);
      await refresh();
    } catch (revokeError) {
      setError(revokeError instanceof Error ? revokeError.message : t("errors.revoke"));
    } finally {
      setRevokingId(null);
    }
  }

  async function handleCopy(): Promise<void> {
    if (!createdSecret) return;
    await navigator.clipboard.writeText(createdSecret);
    setCopied(true);
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
      <div className="mx-auto max-w-3xl space-y-6">
        <div className="flex items-center gap-3">
          <div className="rounded-lg border border-border bg-background p-2 text-muted-foreground">
            <KeyRound className="h-4 w-4" />
          </div>
          <div>
            <h2 className="text-lg font-semibold tracking-tight">{t("title")}</h2>
            <p className="text-sm text-muted-foreground">{t("description")}</p>
          </div>
        </div>

        {error ? (
          <div className="rounded-2xl bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        ) : null}

        {createdSecret ? (
          <div className="space-y-3 rounded-2xl border border-warning/40 bg-warning/10 px-4 py-3 text-foreground">
            <p className="text-sm font-medium">{t("secret.warning")}</p>
            <div className="flex items-center gap-2">
              <code className="min-w-0 flex-1 break-all rounded-md border border-warning/40 bg-background px-3 py-2 font-mono text-xs text-foreground">
                {createdSecret}
              </code>
              <button
                type="button"
                onClick={() => void handleCopy()}
                className={cn(iconButtonClassName, "shrink-0")}
                aria-label={t("secret.copy")}
                title={t("secret.copy")}
              >
                {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
              </button>
            </div>
            <button
              type="button"
              onClick={() => setCreatedSecret(null)}
              className="text-sm font-medium underline underline-offset-2"
            >
              {t("secret.done")}
            </button>
          </div>
        ) : null}

        <form onSubmit={(event) => void handleCreate(event)} className="space-y-4 rounded-2xl bg-surface p-4">
          <label className="space-y-1.5">
            <span className="text-xs font-medium text-muted-foreground">{t("create.nameLabel")}</span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={t("create.namePlaceholder")}
              className={inputClassName}
            />
          </label>

          <div className="space-y-2">
            <span className="text-xs font-medium text-muted-foreground">{t("create.scopesLabel")}</span>
            <div className="space-y-1.5">
              {scopes.map((scope) => {
                const value = grants[scope] ?? "none";
                return (
                  <div key={scope} className="flex items-center justify-between gap-3 rounded-lg border border-border/70 bg-background px-3 py-2">
                    <span className="text-sm font-medium">{t(`scopes.${scope}`)}</span>
                    <div className="flex items-center gap-1">
                      {(["none", "read", "write"] as const).map((access) => (
                        <button
                          key={access}
                          type="button"
                          onClick={() => setAccess(scope, access)}
                          className={cn(
                            "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                            value === access
                              ? "bg-primary text-primary-foreground"
                              : "text-muted-foreground hover:bg-muted hover:text-foreground",
                          )}
                        >
                          {t(`access.${access}`)}
                        </button>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <label className="space-y-1.5">
            <span className="text-xs font-medium text-muted-foreground">{t("create.expiryLabel")}</span>
            <input
              type="number"
              min={1}
              value={expiresInDays}
              onChange={(event) => setExpiresInDays(event.target.value)}
              placeholder={t("create.expiryPlaceholder")}
              className={inputClassName}
            />
          </label>

          <button
            type="submit"
            disabled={creating || !server.trim()}
            className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            {creating ? t("create.creating") : t("create.submit")}
          </button>
        </form>

        <div className="space-y-2">
          <div className="text-xs font-medium text-muted-foreground">{t("list.title")}</div>
          {loading ? (
            <div className="flex items-center gap-2 rounded-lg border border-dashed border-border px-4 py-5 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t("list.loading")}
            </div>
          ) : keys.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border px-4 py-6 text-sm text-muted-foreground">
              {t("list.empty")}
            </div>
          ) : (
            <div className="space-y-2">
              {keys.map((key) => {
                const expired = key.expires_at != null && Date.parse(key.expires_at) <= loadedAtMs;
                return (
                <div key={key.id} className="flex items-start gap-3 rounded-lg border border-border bg-background px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className={cn("truncate text-sm font-semibold", expired && "text-muted-foreground")}>
                        {key.name || t("list.unnamed")}
                      </span>
                      <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 font-mono text-[11px] text-muted-foreground">
                        {key.prefix}…
                      </span>
                      {expired ? (
                        <span className="shrink-0 rounded-full bg-destructive/10 px-2 py-0.5 text-[11px] font-medium text-destructive">
                          {t("list.expired")}
                        </span>
                      ) : null}
                    </div>
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {key.scopes.map((scope) => (
                        <span key={scope} className="rounded-full bg-accent px-2 py-0.5 font-mono text-[11px] text-accent-foreground">
                          {scope}
                        </span>
                      ))}
                    </div>
                    <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground">
                      <span>{t("fields.created", { timestamp: formatTimestamp(key.created_at, t("fields.never")) })}</span>
                      <span>{t("fields.lastUsed", { timestamp: formatTimestamp(key.last_used_at, t("fields.never")) })}</span>
                      <span>{t("fields.expires", { timestamp: formatTimestamp(key.expires_at, t("fields.noExpiry")) })}</span>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => void handleRevoke(key)}
                    title={t("actions.revoke")}
                    aria-label={t("actions.revoke")}
                    className={cn(iconButtonClassName, "hover:bg-destructive/10 hover:text-destructive")}
                    disabled={revokingId !== null || !server.trim()}
                  >
                    {revokingId === key.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                  </button>
                </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
