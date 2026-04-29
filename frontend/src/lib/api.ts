import type {
  HistoryMessage,
  SessionArchiveCommitResponse,
  SessionInfo,
  SessionSandboxSnapshot,
} from "./types";
import { isRecord, readNumber, readString } from "./decoding";

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
  const res = await fetch(`${server}/api/sessions?include_message_count=true`, {
    headers: headers(token),
  });
  if (!res.ok) throw new Error(`Failed to list sessions: ${res.status}`);
  return res.json();
}

export async function createSession(
  server: string,
  token: string,
  options?: { private?: boolean },
): Promise<SessionInfo> {
  const res = await fetch(`${server}/api/sessions`, {
    method: "POST",
    headers: headers(token),
    body: JSON.stringify({ channel_type: "web", ...(options ?? {}) }),
  });
  if (!res.ok) throw new Error(`Failed to create session: ${res.status}`);
  return res.json();
}

export async function updateSession(
  server: string,
  token: string,
  sessionId: string,
  body: { private?: boolean },
): Promise<SessionInfo> {
  const res = await fetch(`${server}/api/sessions/${sessionId}`, {
    method: "PATCH",
    headers: headers(token),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Failed to update session: ${res.status}`);
  return res.json();
}

export async function commitSessionKnowledge(
  server: string,
  token: string,
  sessionId: string,
): Promise<SessionArchiveCommitResponse> {
  const res = await fetch(
    `${server}/api/sessions/${sessionId}/knowledge/commit`,
    {
      method: "POST",
      headers: headers(token),
    },
  );
  if (!res.ok)
    throw new Error(`Failed to commit session knowledge: ${res.status}`);
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

export async function fetchSandbox(
  server: string,
  token: string,
  sessionId: string,
): Promise<SessionSandboxSnapshot> {
  const res = await fetch(`${server}/api/sessions/${sessionId}/sandbox`, {
    headers: headers(token),
  });
  if (!res.ok) throw new Error(`Failed to fetch sandbox: ${res.status}`);
  return res.json();
}

export async function startSandbox(
  server: string,
  token: string,
  sessionId: string,
): Promise<SessionSandboxSnapshot> {
  const res = await fetch(`${server}/api/sessions/${sessionId}/sandbox/up`, {
    method: "POST",
    headers: headers(token),
  });
  if (!res.ok) throw new Error(`Failed to start sandbox: ${res.status}`);
  return res.json();
}

export async function stopSandbox(
  server: string,
  token: string,
  sessionId: string,
): Promise<SessionSandboxSnapshot> {
  const res = await fetch(`${server}/api/sessions/${sessionId}/sandbox/down`, {
    method: "POST",
    headers: headers(token),
  });
  if (!res.ok) throw new Error(`Failed to scale down sandbox: ${res.status}`);
  return res.json();
}

export async function wipeSandbox(
  server: string,
  token: string,
  sessionId: string,
): Promise<SessionSandboxSnapshot> {
  const res = await fetch(`${server}/api/sessions/${sessionId}/sandbox/wipe`, {
    method: "POST",
    headers: headers(token),
  });
  if (!res.ok) throw new Error(`Failed to wipe sandbox: ${res.status}`);
  return res.json();
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

function decodeSlashCommand(raw: unknown): SlashCommand | null {
  if (!isRecord(raw)) return null;

  const command = readString(raw, "command");
  const description = readString(raw, "description");
  if (!command || description === undefined) return null;

  return { command, description };
}

function decodeSlashCommands(raw: unknown): SlashCommand[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((item) => decodeSlashCommand(item))
    .filter((item): item is SlashCommand => item !== null);
}

export async function fetchCommands(
  server: string,
  token: string,
): Promise<SlashCommand[]> {
  const res = await fetch(`${server}/api/commands`, {
    headers: headers(token),
  });
  if (!res.ok) return [];
  const raw: unknown = await res.json();
  return decodeSlashCommands(raw);
}

export interface AvailableModelInfo {
  id: string;
  provider: string;
  name: string;
  max_input_tokens?: number | null;
}

export function decodeAvailableModel(raw: unknown): AvailableModelInfo | null {
  if (typeof raw === "string") {
    const splitIndex = raw.indexOf(":");
    if (splitIndex === -1) {
      return { id: raw, provider: "", name: raw, max_input_tokens: null };
    }

    return {
      id: raw,
      provider: raw.slice(0, splitIndex),
      name: raw.slice(splitIndex + 1),
      max_input_tokens: null,
    };
  }

  if (!isRecord(raw)) return null;

  const rawId =
    readString(raw, "id") ??
    (typeof raw.id === "number" ? String(raw.id) : undefined);
  if (!rawId) return null;

  return {
    id: rawId,
    provider: readString(raw, "provider") ?? "",
    name: readString(raw, "name") ?? "",
    max_input_tokens: readNumber(raw, "max_input_tokens") ?? null,
  };
}

function decodeAvailableModels(raw: unknown): AvailableModelInfo[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((item) => decodeAvailableModel(item))
    .filter((item): item is AvailableModelInfo => item !== null);
}

export async function fetchModels(
  server: string,
  token: string,
): Promise<AvailableModelInfo[]> {
  const res = await fetch(`${server}/api/models`, { headers: headers(token) });
  if (!res.ok) return [];
  const raw: unknown = await res.json();
  return decodeAvailableModels(raw);
}

export function wsUrl(
  server: string,
  sessionId: string,
  token: string,
): string {
  const base = server.replace("http://", "ws://").replace("https://", "wss://");
  return `${base}/api/chat/${sessionId}?token=${token}`;
}
