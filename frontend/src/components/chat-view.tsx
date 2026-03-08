"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { useWebSocket } from "@/hooks/use-websocket";
import { fetchCommands, fetchHistory, wsUrl } from "@/lib/api";
import type { SlashCommand } from "@/lib/api";
import type { ChatMessage, ServerMessage, TurnUsage } from "@/lib/types";
import { Message } from "./message";
import { ChatInput } from "./chat-input";

interface ChatViewProps {
  server: string;
  token: string;
  sessionId: string;
  onTitleUpdate?: (title: string) => void;
}

export function ChatView({ server, token, sessionId, onTitleUpdate }: ChatViewProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [waiting, setWaiting] = useState(false);
  const [queuedMessage, setQueuedMessage] = useState<string | null>(null);
  const [usage, setUsage] = useState<TurnUsage | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [commands, setCommands] = useState<SlashCommand[]>([]);
  const approvalState = useRef<Map<string, boolean>>(new Map());
  const bottomRef = useRef<HTMLDivElement>(null);
  const messagesRef = useRef<ChatMessage[]>([]);
  messagesRef.current = messages;

  // Fetch available slash commands on mount
  useEffect(() => {
    fetchCommands(server, token).then(setCommands);
  }, [server, token]);

  // Load history on mount / session change
  useEffect(() => {
    let cancelled = false;
    setMessages([]);
    setLoadingHistory(true);
    setQueuedMessage(null);
    approvalState.current.clear();

    fetchHistory(server, token, sessionId)
      .then((history) => {
        if (cancelled) return;
        const msgs: ChatMessage[] = [];
        for (let i = 0; i < history.length; i++) {
          const h = history[i];
          if (h.role === "user") {
            msgs.push({ kind: "user", content: h.content });
          } else if (h.role === "tool_call") {
            // Look ahead for a matching tool_result
            const next = history[i + 1];
            const result =
              next?.role === "tool_result" && next.tool === h.tool
                ? next.result
                : undefined;
            msgs.push({
              kind: "tool_call",
              tool: h.tool ?? "",
              args: h.args ?? {},
              detail: h.detail ?? "",
              result: result ?? undefined,
            });
          } else if (h.role === "tool_result") {
            // Skip — already consumed by the tool_call above
          } else if (h.role === "approval_request" && h.tool_call_id) {
            approvalState.current.set(h.tool_call_id, true);
            msgs.push({
              kind: "approval",
              request: {
                type: "approval_request",
                tool_call_id: h.tool_call_id,
                tool: h.tool ?? "",
                args: (h.args ?? {}) as Record<string, unknown>,
                explanation: h.explanation ?? "",
                risk_level: h.risk_level ?? "",
              },
            });
          } else if (h.role === "proxy_approval" && h.request_id) {
            // Proxy approval: first event is the request, second has the decision
            if (!h.decision) {
              // Look ahead for the matching decision event
              const next = history[i + 1];
              const decision =
                next?.role === "proxy_approval" &&
                next.request_id === h.request_id
                  ? (next.decision as import("@/lib/types").DomainDecision)
                  : undefined;
              msgs.push({
                kind: "proxy_approval",
                request: {
                  type: "proxy_approval_request",
                  request_id: h.request_id,
                  domain: h.domain ?? "",
                  command: h.command ?? "",
                },
                decision,
              });
            }
            // Skip decision-only events (consumed above)
          } else if (h.role === "command") {
            msgs.push({
              kind: "command",
              command: h.command ?? "",
              data: h.data,
            });
          } else {
            msgs.push({ kind: "assistant", content: h.content });
          }
        }
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
        if (msg.usage) setUsage(msg.usage);
        setWaiting(false);
        break;
      case "tool_call": {
        const isLoading =
          msg.tool !== "proxy_domain" &&
          !msg.detail.includes("deny]") &&
          !msg.detail.includes("escalate]");
        setMessages((prev) => [
          ...prev,
          {
            kind: "tool_call",
            tool: msg.tool,
            args: msg.args,
            detail: msg.detail,
            loading: isLoading,
          },
        ]);
        break;
      }
      case "tool_result":
        setMessages((prev) => {
          const updated = [...prev];
          for (let i = updated.length - 1; i >= 0; i--) {
            const m = updated[i];
            if (m.kind === "tool_call" && m.loading && m.tool === msg.tool) {
              updated[i] = { ...m, result: msg.result, loading: false };
              break;
            }
          }
          return updated;
        });
        break;
      case "approval_request":
        setMessages((prev) => [...prev, { kind: "approval", request: msg }]);
        break;
      case "proxy_approval_request":
        setMessages((prev) => [
          ...prev,
          { kind: "proxy_approval", request: msg },
        ]);
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
      case "cancelled":
        setMessages((prev) => [
          ...prev,
          { kind: "error", detail: msg.detail },
        ]);
        setWaiting(false);
        break;
      case "session_title":
        onTitleUpdate?.(msg.title);
        break;
      case "token":
        // future streaming support
        break;
    }
  }, [onTitleUpdate]);

  const onWsDisconnect = useCallback(() => setWaiting(false), []);
  const url = wsUrl(server, sessionId, token);
  const { status, send } = useWebSocket(url, onMessage, onWsDisconnect);

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Flush queued message when agent finishes and connection is up
  useEffect(() => {
    if (!waiting && queuedMessage && status === "connected") {
      const msg = queuedMessage;
      setQueuedMessage(null);
      send({ type: "message", content: msg });
      setWaiting(true);
    }
  }, [waiting, queuedMessage, status, send]);

  // Clear queue on disconnect
  useEffect(() => {
    if (status !== "connected") {
      setQueuedMessage(null);
    }
  }, [status]);

  function handleSend(content: string) {
    setMessages((prev) => [...prev, { kind: "user", content }]);
    if (waiting) {
      setQueuedMessage(content);
    } else {
      send({ type: "message", content });
      setWaiting(true);
    }
  }

  function handleInterrupt(content: string) {
    setQueuedMessage(content);
    setMessages((prev) => [...prev, { kind: "user", content }]);
    send({ type: "cancel" });
  }

  function handleApproval(toolCallId: string, approved: boolean) {
    approvalState.current.set(toolCallId, approved);
    send({ type: "approval_response", tool_call_id: toolCallId, approved });
    // Force re-render to show resolved state
    setMessages((prev) => [...prev]);
  }

  function handleProxyApproval(
    requestId: string,
    decision: import("@/lib/types").DomainDecision,
  ) {
    send({ type: "proxy_approval_response", request_id: requestId, decision });
    setMessages((prev) =>
      prev.map((m) =>
        m.kind === "proxy_approval" && m.request.request_id === requestId
          ? { ...m, decision }
          : m,
      ),
    );
  }

  function handleCancel() {
    send({ type: "cancel" });
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
              onProxyApproval={handleProxyApproval}
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
      <ChatInput
        onSend={handleSend}
        onCancel={handleCancel}
        onInterrupt={handleInterrupt}
        connected={connected}
        waiting={waiting}
        hasQueuedMessage={queuedMessage !== null}
        commands={commands}
        usage={usage}
      />
    </div>
  );
}
