"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { useWebSocket } from "@/hooks/use-websocket";
import { fetchCommands, fetchHistory, fetchModels, wsUrl } from "@/lib/api";
import type { SlashCommand } from "@/lib/api";
import type { ChatMessage, ClientMessage, EscalationDecision, ServerMessage, TurnUsage } from "@/lib/types";
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
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [approvalState, setApprovalState] = useState<Map<string, boolean>>(new Map());
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const isAtBottomRef = useRef(true);
  const queueRef = useRef<string | null>(null);
  const sendRef = useRef<(msg: ClientMessage) => void>(() => {});

  // Fetch available slash commands and models on mount
  useEffect(() => {
    fetchCommands(server, token).then(setCommands);
    fetchModels(server, token).then(setAvailableModels);
  }, [server, token]);

  // Load history on mount
  useEffect(() => {
    let cancelled = false;

    fetchHistory(server, token, sessionId)
      .then((history) => {
        if (cancelled) return;
        const msgs: ChatMessage[] = [];
        const approvals = new Map<string, boolean>();
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
          } else if (h.role === "approval_response") {
            // Skip — consumed by the approval_request above
          } else if (h.role === "approval_request" && h.tool_call_id) {
            // Look ahead for a matching approval_response
            const response = history.find(
              (r) => r.role === "approval_response" && r.tool_call_id === h.tool_call_id,
            );
            if (response) {
              approvals.set(h.tool_call_id, response.decision === "approved");
            }
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
          } else if ((h.role === "domain_access_approval" || h.role === "proxy_approval") && h.request_id) {
            // Domain access approval: first event is the request, second has the decision
            if (!h.decision) {
              // Look ahead for the matching decision event
              const next = history[i + 1];
              const decision =
                (next?.role === "domain_access_approval" || next?.role === "proxy_approval") &&
                next.request_id === h.request_id
                  ? (next.decision as EscalationDecision)
                  : undefined;
              msgs.push({
                kind: "domain_access_approval",
                request: {
                  type: "domain_access_approval_request",
                  request_id: h.request_id,
                  domain: h.domain ?? "",
                  command: h.command ?? "",
                },
                decision,
              });
            }
            // Skip decision-only events (consumed above)
          } else if (h.role === "git_push_approval" && h.request_id) {
            // Git push approval: first event is the request, second has the decision
            if (!h.decision) {
              const next = history[i + 1];
              const decision =
                next?.role === "git_push_approval" &&
                next.request_id === h.request_id
                  ? (next.decision as EscalationDecision)
                  : undefined;
              msgs.push({
                kind: "git_push_approval",
                request: {
                  type: "git_push_approval_request",
                  request_id: h.request_id,
                  ref: h.ref ?? "",
                  explanation: h.explanation ?? "",
                  changed_files: (h.changed_files as string[] | undefined) ?? [],
                },
                decision,
              });
            }
          } else if (h.role === "git_push") {
            msgs.push({
              kind: "tool_call",
              tool: "git_push",
              args: { ref: h.ref ?? "", decision: h.decision ?? "" },
              detail: h.detail ?? "",
            });
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
        setApprovalState(approvals);
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
    // sessionId excluded: component remounts (via key) on session change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [server, token]);

  // Flush a queued message if present, otherwise mark as not-waiting
  function finishWaiting() {
    const queued = queueRef.current;
    if (queued) {
      queueRef.current = null;
      setQueuedMessage(null);
      sendRef.current({ type: "message", content: queued });
      // stay in waiting state
    } else {
      setWaiting(false);
    }
  }

  const onMessage = useCallback((msg: ServerMessage) => {
    switch (msg.type) {
      case "done":
        setMessages((prev) => {
          // Replace trailing streaming message with the final content
          if (prev.length > 0 && prev[prev.length - 1].kind === "streaming") {
            return [
              ...prev.slice(0, -1),
              { kind: "assistant", content: msg.content },
            ];
          }
          return [...prev, { kind: "assistant", content: msg.content }];
        });
        if (msg.usage) setUsage(msg.usage);
        finishWaiting();
        break;
      case "tool_call": {
        const isGitPush = msg.tool === "git_push";
        if (!isGitPush) setWaiting(true); // agent is active (may restore after reconnect)
        const isLoading =
          msg.tool !== "proxy_domain" &&
          !isGitPush &&
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
        if (isGitPush) finishWaiting();
        break;
      }
      case "tool_result":
        setWaiting(true);
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
        setWaiting(true);
        setMessages((prev) => [...prev, { kind: "approval", request: msg }]);
        break;
      case "domain_access_approval_request":
        setWaiting(true);
        setMessages((prev) => [
          ...prev,
          { kind: "domain_access_approval", request: msg },
        ]);
        break;
      case "git_push_approval_request":
        setWaiting(true);
        setMessages((prev) => [
          ...prev,
          { kind: "git_push_approval", request: msg },
        ]);
        break;
      case "command_result":
        setMessages((prev) => [
          ...prev,
          { kind: "command", command: msg.command, data: msg.data },
        ]);
        finishWaiting();
        break;
      case "error":
        setMessages((prev) => [...prev, { kind: "error", detail: msg.detail }]);
        finishWaiting();
        break;
      case "cancelled":
        setMessages((prev) => [
          ...prev,
          { kind: "error", detail: msg.detail },
        ]);
        finishWaiting();
        break;
      case "session_title":
        onTitleUpdate?.(msg.title);
        break;
      case "status":
        if (msg.agent_running) setWaiting(true);
        if (msg.usage) setUsage(msg.usage);
        break;
      case "user_message":
        setWaiting(true);
        setMessages((prev) => [
          ...prev,
          { kind: "user", content: msg.content },
        ]);
        break;
      case "token":
        setWaiting(true);
        setMessages((prev) => {
          if (prev.length > 0 && prev[prev.length - 1].kind === "streaming") {
            const last = prev[prev.length - 1] as { kind: "streaming"; content: string };
            return [
              ...prev.slice(0, -1),
              { kind: "streaming", content: last.content + msg.content },
            ];
          }
          return [...prev, { kind: "streaming", content: msg.content }];
        });
        break;
    }
  }, [onTitleUpdate]);

  const onWsDisconnect = useCallback(() => {
    queueRef.current = null;
    setQueuedMessage(null);
    setWaiting(false);
  }, []);
  const url = wsUrl(server, sessionId, token);
  const { status, send } = useWebSocket(url, onMessage, onWsDisconnect);
  useEffect(() => { sendRef.current = send; }, [send]);

  // Auto-scroll only when already at bottom
  useEffect(() => {
    if (isAtBottomRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const threshold = 64;
    isAtBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < threshold;
  }, []);

  function handleSend(content: string) {
    if (waiting) {
      queueRef.current = content;
      setQueuedMessage(content);
    } else {
      send({ type: "message", content });
      setWaiting(true);
    }
  }

  function handleInterrupt(content: string) {
    queueRef.current = content;
    setQueuedMessage(content);
    send({ type: "cancel" });
  }

  function handleApproval(toolCallId: string, approved: boolean) {
    setApprovalState((prev) => new Map(prev).set(toolCallId, approved));
    send({ type: "approval_response", tool_call_id: toolCallId, approved });
    // Force re-render to show resolved state
    setMessages((prev) => [...prev]);
  }

  function handleEscalation(
    requestId: string,
    decision: EscalationDecision,
  ) {
    send({ type: "escalation_response", request_id: requestId, decision });
    setMessages((prev) =>
      prev.map((m) =>
        (m.kind === "domain_access_approval" || m.kind === "git_push_approval") &&
        m.request.request_id === requestId
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
    <div className="flex flex-1 min-h-0 flex-col">
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
      <div ref={scrollRef} onScroll={handleScroll} className="flex-1 overflow-y-auto px-4 py-4">
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
                  ? approvalState.get(msg.request.tool_call_id)
                  : undefined
              }
              onEscalation={handleEscalation}
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
        queuedMessage={queuedMessage}
        commands={commands}
        availableModels={availableModels}
        usage={usage}
      />
    </div>
  );
}
