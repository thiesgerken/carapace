"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { useWebSocket } from "@/hooks/use-websocket";
import { fetchHistory, wsUrl } from "@/lib/api";
import type { ChatMessage, ServerMessage } from "@/lib/types";
import { Message } from "./message";
import { ChatInput } from "./chat-input";

interface ChatViewProps {
  server: string;
  token: string;
  sessionId: string;
}

export function ChatView({ server, token, sessionId }: ChatViewProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [waiting, setWaiting] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const approvalState = useRef<Map<string, boolean>>(new Map());
  const bottomRef = useRef<HTMLDivElement>(null);
  const messagesRef = useRef<ChatMessage[]>([]);
  messagesRef.current = messages;

  // Load history on mount / session change
  useEffect(() => {
    let cancelled = false;
    setMessages([]);
    setLoadingHistory(true);
    approvalState.current.clear();

    fetchHistory(server, token, sessionId)
      .then((history) => {
        if (cancelled) return;
        const msgs: ChatMessage[] = history.map((h) => {
          if (h.role === "user") return { kind: "user", content: h.content };
          if (h.role === "tool_call")
            return {
              kind: "tool_call",
              tool: h.tool ?? "",
              args: h.args ?? {},
              detail: "",
            };
          if (h.role === "command")
            return {
              kind: "command",
              command: h.command ?? "",
              data: h.data,
            };
          return { kind: "assistant", content: h.content };
        });
        setMessages(msgs);
      })
      .catch(() => {
        // history fetch can fail for new sessions - that's fine
      })
      .finally(() => {
        if (!cancelled) setLoadingHistory(false);
      });

    return () => {
      cancelled = true;
    };
  }, [server, token, sessionId]);

  const onMessage = useCallback((msg: ServerMessage) => {
    switch (msg.type) {
      case "done":
        setMessages((prev) => [
          ...prev,
          { kind: "assistant", content: msg.content },
        ]);
        setWaiting(false);
        break;
      case "tool_call":
        setMessages((prev) => [
          ...prev,
          {
            kind: "tool_call",
            tool: msg.tool,
            args: msg.args,
            detail: msg.detail,
          },
        ]);
        break;
      case "approval_request":
        setMessages((prev) => [...prev, { kind: "approval", request: msg }]);
        break;
      case "command_result":
        setMessages((prev) => [
          ...prev,
          { kind: "command", command: msg.command, data: msg.data },
        ]);
        setWaiting(false);
        break;
      case "error":
        setMessages((prev) => [...prev, { kind: "error", detail: msg.detail }]);
        setWaiting(false);
        break;
      case "token":
        // future streaming support
        break;
    }
  }, []);

  const onWsDisconnect = useCallback(() => setWaiting(false), []);
  const url = wsUrl(server, sessionId, token);
  const { status, send } = useWebSocket(url, onMessage, onWsDisconnect);

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function handleSend(content: string) {
    setMessages((prev) => [...prev, { kind: "user", content }]);
    send({ type: "message", content });
    setWaiting(true);
  }

  function handleApproval(toolCallId: string, approved: boolean) {
    approvalState.current.set(toolCallId, approved);
    send({ type: "approval_response", tool_call_id: toolCallId, approved });
    // Force re-render to show resolved state
    setMessages((prev) => [...prev]);
  }

  const connected = status === "connected";

  return (
    <div className="flex h-full flex-col">
      {/* Status bar */}
      {status !== "connected" && (
        <div className="flex items-center gap-2 border-b border-border px-4 py-2 text-xs text-muted-foreground">
          <span
            className={`h-1.5 w-1.5 rounded-full ${status === "connecting" ? "bg-warning animate-pulse" : "bg-destructive"}`}
          />
          {status === "connecting" ? "Connecting…" : "Disconnected"}
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        <div className="mx-auto max-w-3xl space-y-3">
          {loadingHistory && (
            <div className="flex justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          )}
          {!loadingHistory && messages.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <p className="text-lg font-medium text-foreground/80">Carapace</p>
              <p className="mt-1 text-sm text-muted-foreground">
                {connected
                  ? "Send a message to get started"
                  : "Connecting to session…"}
              </p>
            </div>
          )}
          {messages.map((msg, i) => (
            <Message
              key={i}
              message={msg}
              onApproval={handleApproval}
              approvalResolved={
                msg.kind === "approval"
                  ? approvalState.current.get(msg.request.tool_call_id)
                  : undefined
              }
            />
          ))}
          {waiting && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              <span>Thinking…</span>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* Input */}
      <ChatInput onSend={handleSend} disabled={!connected || waiting} />
    </div>
  );
}
