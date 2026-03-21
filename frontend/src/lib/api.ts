import type { HistoryMessage, SessionInfo } from "./types";

function headers(token: string): HeadersInit {
  return {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
}

export async function listSessions(
  server: string,
  token: string,
): Promise<SessionInfo[]> {
  const res = await fetch(`${server}/api/sessions`, {
    headers: headers(token),
  });
  if (!res.ok) throw new Error(`Failed to list sessions: ${res.status}`);
  return res.json();
}

export async function createSession(
  server: string,
  token: string,
): Promise<SessionInfo> {
  const res = await fetch(`${server}/api/sessions`, {
    method: "POST",
    headers: headers(token),
    body: JSON.stringify({ channel_type: "web" }),
  });
  if (!res.ok) throw new Error(`Failed to create session: ${res.status}`);
  return res.json();
}

export async function deleteSession(
  server: string,
  token: string,
  sessionId: string,
): Promise<void> {
  const res = await fetch(`${server}/api/sessions/${sessionId}`, {
    method: "DELETE",
    headers: headers(token),
  });
  if (!res.ok) throw new Error(`Failed to delete session: ${res.status}`);
}

export async function fetchHistory(
  server: string,
  token: string,
  sessionId: string,
): Promise<HistoryMessage[]> {
  const res = await fetch(`${server}/api/sessions/${sessionId}/history`, {
    headers: headers(token),
  });
  if (!res.ok) throw new Error(`Failed to fetch history: ${res.status}`);
  return res.json();
}

export interface SlashCommand {
  command: string;
  description: string;
}

export async function fetchCommands(
  server: string,
  token: string,
): Promise<SlashCommand[]> {
  const res = await fetch(`${server}/api/commands`, {
    headers: headers(token),
  });
  if (!res.ok) return [];
  return res.json();
}

export async function fetchModels(
  server: string,
  token: string,
): Promise<string[]> {
  const res = await fetch(`${server}/api/models`, { headers: headers(token) });
  if (!res.ok) return [];
  return res.json();
}

export function wsUrl(
  server: string,
  sessionId: string,
  token: string,
): string {
  const base = server.replace("http://", "ws://").replace("https://", "wss://");
  return `${base}/api/chat/${sessionId}?token=${token}`;
}
