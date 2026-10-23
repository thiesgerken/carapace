"use client";

import Image from "next/image";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { login, type AuthUserInfo } from "@/lib/api";
import { getServer, getToken } from "@/lib/storage";
import { cn } from "@/lib/utils";

interface ConnectFormProps {
  onConnect: (user: AuthUserInfo) => void;
}

export function ConnectForm({ onConnect }: ConnectFormProps) {
  const t = useTranslations("connect");
  const [username, setUsername] = useState(getToken);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const user = await login(getServer(), username, password);
      onConnect(user);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("errors.connectionFailed"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-4">
        <div className="space-y-1.5 text-center">
          <h1>
            <Image src="/logo-light.svg" alt="carapace" width={561} height={109} priority className="mx-auto h-auto w-70 max-w-full dark:hidden" />
            <Image src="/logo-dark.svg" alt="carapace" width={561} height={109} priority className="mx-auto hidden h-auto w-70 max-w-full dark:block" />
          </h1>
          <p className="text-sm text-muted-foreground">
            {t("description")}
          </p>
        </div>

        <div className="space-y-3">
          <div className="space-y-1.5">
            <label
              htmlFor="username"
              className="text-xs font-medium text-muted-foreground"
            >
              {t("usernameLabel")}
            </label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder={t("usernamePlaceholder")}
              required
              className={cn(
                "w-full rounded-lg border border-border bg-background px-3 py-2.5 text-base sm:text-sm",
                "outline-none transition-colors",
                "focus:ring-2 focus:ring-ring/30 focus:border-ring",
                "placeholder:text-muted-foreground/50",
              )}
            />
          </div>

          <div className="space-y-1.5">
            <label
              htmlFor="password"
              className="text-xs font-medium text-muted-foreground"
            >
              {t("passwordLabel")}
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={t("passwordPlaceholder")}
              required
              className={cn(
                "w-full rounded-lg border border-border bg-background px-3 py-2.5 text-base sm:text-sm",
                "outline-none transition-colors",
                "focus:ring-2 focus:ring-ring/30 focus:border-ring",
                "placeholder:text-muted-foreground/50",
              )}
            />
          </div>
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <button
          type="submit"
          disabled={loading || !username || !password}
          className={cn(
            "w-full rounded-lg px-4 py-2 text-sm font-medium transition-colors",
            "bg-foreground text-background",
            "hover:bg-foreground/90",
            "disabled:opacity-50 disabled:cursor-not-allowed",
          )}
        >
          {loading ? t("connecting") : t("connect")}
        </button>
      </form>
    </div>
  );
}
