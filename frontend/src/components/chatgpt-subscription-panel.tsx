"use client";

import { ExternalLink, Link2Off, Loader2, LogIn, RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import {
  completeCodexLogin,
  disconnectCodex,
  getCodexStatus,
  startCodexLogin,
  type CodexStatusInfo,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const buttonClassName = cn(
  "inline-flex min-h-9 items-center justify-center gap-2 rounded-lg border border-border bg-background px-3 py-2",
  "text-sm font-medium transition-colors hover:bg-muted/60 disabled:cursor-not-allowed disabled:opacity-50",
);

const inputClassName = cn(
  "w-full rounded-xl border border-border bg-background px-3 py-2.5 text-sm",
  "outline-none transition-colors placeholder:text-muted-foreground/50",
  "focus:border-ring focus:ring-2 focus:ring-ring/30",
);

// Acts immediately through its own endpoints instead of the settings form's save draft: the login
// is a multi-step exchange with OpenAI, and the stored tokens are never part of the settings blob.
export function ChatGptSubscriptionPanel({ server, token }: { server: string; token: string }) {
  const t = useTranslations("accountSettings.chatgpt");
  const [status, setStatus] = useState<CodexStatusInfo | null>(null);
  const [authorizeUrl, setAuthorizeUrl] = useState<string | null>(null);
  const [redirectUrl, setRedirectUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : t("errors.generic"));
    } finally {
      setBusy(false);
    }
  }, [t]);

  useEffect(() => {
    let cancelled = false;
    getCodexStatus(server, token).then(
      (next) => {
        if (!cancelled) setStatus(next);
      },
      (loadError: unknown) => {
        if (!cancelled) setError(loadError instanceof Error ? loadError.message : t("errors.generic"));
      },
    );
    return () => {
      cancelled = true;
    };
  }, [server, t, token]);

  const startLogin = () => run(async () => {
    setAuthorizeUrl(await startCodexLogin(server, token));
    setRedirectUrl("");
  });

  const completeLogin = () => run(async () => {
    setStatus(await completeCodexLogin(server, token, redirectUrl.trim()));
    setAuthorizeUrl(null);
    setRedirectUrl("");
  });

  const disconnect = () => run(async () => {
    await disconnectCodex(server, token);
    setStatus({ connected: false, email: null, updated_at: null });
    setAuthorizeUrl(null);
  });

  if (status === null) {
    return (
      <div className={cn("flex items-center gap-2 text-sm", error ? "text-destructive" : "text-muted-foreground")}>
        {error ?? <><Loader2 className="h-4 w-4 animate-spin" />{t("status.loading")}</>}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">{t("description")}</p>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm">
          {status.connected
            ? status.email
              ? t("status.connectedAs", { email: status.email })
              : t("status.connected")
            : t("status.notConnected")}
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={() => void startLogin()} disabled={busy} className={buttonClassName}>
            {status.connected ? <RefreshCw className="h-4 w-4" /> : <LogIn className="h-4 w-4" />}
            {status.connected ? t("actions.reconnect") : t("actions.connect")}
          </button>
          {status.connected ? (
            <button
              type="button"
              onClick={() => void disconnect()}
              disabled={busy}
              className={cn(buttonClassName, "hover:bg-destructive/10 hover:text-destructive")}
            >
              <Link2Off className="h-4 w-4" />
              {t("actions.disconnect")}
            </button>
          ) : null}
        </div>
      </div>

      {authorizeUrl ? (
        <ol className="list-decimal space-y-3 rounded-lg border border-border bg-muted/20 p-4 pl-8 text-sm">
          <li>
            <a
              href={authorizeUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 font-medium underline underline-offset-4"
            >
              {t("steps.open")}
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          </li>
          <li className="text-muted-foreground">{t("steps.redirect")}</li>
          <li className="space-y-2">
            <span className="block text-muted-foreground">{t("steps.paste")}</span>
            <div className="flex flex-col gap-2 sm:flex-row">
              <input
                value={redirectUrl}
                onChange={(event) => setRedirectUrl(event.target.value)}
                onKeyDown={(event) => {
                  // The panel sits inside the settings form; Enter must not submit that form.
                  if (event.key !== "Enter") return;
                  event.preventDefault();
                  if (redirectUrl.trim()) void completeLogin();
                }}
                placeholder="http://localhost:1455/auth/callback?code=…"
                autoComplete="off"
                className={cn(inputClassName, "min-w-0 flex-1")}
              />
              <button
                type="button"
                onClick={() => void completeLogin()}
                disabled={busy || !redirectUrl.trim()}
                className={buttonClassName}
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                {t("actions.complete")}
              </button>
            </div>
          </li>
        </ol>
      ) : null}

      {error ? <div className="text-sm text-destructive">{error}</div> : null}
    </div>
  );
}
