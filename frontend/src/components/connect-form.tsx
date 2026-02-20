"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";

interface ConnectFormProps {
  onConnect: (server: string, token: string) => void;
}

export function ConnectForm({ onConnect }: ConnectFormProps) {
  const [server, setServer] = useState("http://127.0.0.1:8321");
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const res = await fetch(`${server.replace(/\/$/, "")}/sessions`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok)
        throw new Error(
          res.status === 401 ? "Invalid token" : `Server error: ${res.status}`,
        );
      onConnect(server.replace(/\/$/, ""), token);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Connection failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-4">
        <div className="space-y-1.5 text-center">
          <h1 className="text-xl font-semibold tracking-tight">Carapace</h1>
          <p className="text-sm text-muted-foreground">
            Connect to your server
          </p>
        </div>

        <div className="space-y-3">
          <div className="space-y-1.5">
            <label
              htmlFor="server"
              className="text-xs font-medium text-muted-foreground"
            >
              Server URL
            </label>
            <input
              id="server"
              type="url"
              value={server}
              onChange={(e) => setServer(e.target.value)}
              placeholder="http://127.0.0.1:8321"
              required
              className={cn(
                "w-full rounded-lg border border-border bg-background px-3 py-2 text-sm",
                "outline-none transition-colors",
                "focus:ring-2 focus:ring-ring/30 focus:border-ring",
                "placeholder:text-muted-foreground/50",
              )}
            />
          </div>

          <div className="space-y-1.5">
            <label
              htmlFor="token"
              className="text-xs font-medium text-muted-foreground"
            >
              Bearer Token
            </label>
            <input
              id="token"
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="Paste your token"
              required
              className={cn(
                "w-full rounded-lg border border-border bg-background px-3 py-2 text-sm font-mono",
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
          disabled={loading || !token}
          className={cn(
            "w-full rounded-lg px-4 py-2 text-sm font-medium transition-colors",
            "bg-foreground text-background",
            "hover:bg-foreground/90",
            "disabled:opacity-50 disabled:cursor-not-allowed",
          )}
        >
          {loading ? "Connecting…" : "Connect"}
        </button>
      </form>
    </div>
  );
}
