"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getWebSocketTicket } from "@/lib/api";
import type { ClientMessage, ServerMessage } from "@/lib/types";

type Status = "disconnected" | "connecting" | "connected";

const RECONNECT_DELAYS = [500, 1000, 2000, 4000];
// A connection must stay open at least this long before it counts as "stable"
// and the backoff resets. Prevents a tight reconnect loop when the backend
// accepts the socket then immediately drops it (half-ready after a restart).
const STABLE_CONNECTION_MS = 5000;

export function useWebSocket(
  url: string | null,
  onMessage: (msg: ServerMessage) => void,
  onDisconnect?: () => void,
) {
  const [status, setStatus] = useState<Status>("disconnected");
  const wsRef = useRef<WebSocket | null>(null);
  const onMessageRef = useRef(onMessage);
  const onDisconnectRef = useRef(onDisconnect);
  useEffect(() => { onMessageRef.current = onMessage; }, [onMessage]);
  useEffect(() => { onDisconnectRef.current = onDisconnect; }, [onDisconnect]);
  const retriesRef = useRef(0);
  const unmountedRef = useRef(false);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const connectRef = useRef<() => void>(() => {});

  const connect = useCallback(() => {
    if (!url || unmountedRef.current) return;
    let opened = false;
    let openedAt = 0;

    // Close any existing connection before opening a new one
    if (wsRef.current) {
      wsRef.current.onclose = null; // prevent stale onclose from firing
      wsRef.current.close();
      wsRef.current = null;
    }

    // Clear any pending reconnect timer
    if (reconnectTimerRef.current !== null) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }

    setStatus("connecting");
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      if (wsRef.current !== ws) return; // stale
      opened = true;
      openedAt = Date.now();
      setStatus("connected");
      // Do NOT reset retries here: a connection that opens then immediately
      // drops must keep backing off. Reset happens in onclose once the socket
      // has stayed open past STABLE_CONNECTION_MS.
    };

    ws.onclose = () => {
      // Ignore if a newer connection already replaced this one
      if (wsRef.current !== ws) return;
      wsRef.current = null;
      if (opened) {
        onDisconnectRef.current?.();
        if (Date.now() - openedAt >= STABLE_CONNECTION_MS) {
          retriesRef.current = 0;
        }
      }

      if (unmountedRef.current) return;
      setStatus("connecting");
      const delay =
        RECONNECT_DELAYS[
          Math.min(retriesRef.current, RECONNECT_DELAYS.length - 1)
        ];
      retriesRef.current++;
      reconnectTimerRef.current = setTimeout(() => {
        reconnectTimerRef.current = null;
        if (!unmountedRef.current) connectRef.current();
      }, delay);
    };

    ws.onerror = () => {
      // onclose will fire after onerror, reconnect happens there
    };

    ws.onmessage = (event) => {
      if (wsRef.current !== ws) return; // stale
      try {
        const msg = JSON.parse(event.data) as ServerMessage;
        onMessageRef.current(msg);
      } catch {
        // ignore unparseable messages
      }
    };
  }, [url]);
  useEffect(() => { connectRef.current = connect; }, [connect]);

  useEffect(() => {
    unmountedRef.current = false;
    retriesRef.current = 0;
    // Defer to avoid synchronous setState in effect body
    const timer = setTimeout(() => connect(), 0);

    return () => {
      clearTimeout(timer);
      unmountedRef.current = true;
      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.onclose = null; // prevent stale onclose
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect]);

  const send = useCallback((msg: ClientMessage) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
    }
  }, []);

  return { status, send };
}

/** A fresh ticket for opening a session WebSocket; null while it loads or when the request fails. */
export function useWebSocketTicket(server: string, token: string): string | null {
  const key = `${server}\n${token}`;
  const [issued, setIssued] = useState<{ key: string; ticket: string | null } | null>(null);
  useEffect(() => {
    let cancelled = false;
    getWebSocketTicket(server, token)
      .then((ticket) => {
        if (!cancelled) setIssued({ key, ticket });
      })
      .catch(() => {
        if (!cancelled) setIssued({ key, ticket: null });
      });
    return () => {
      cancelled = true;
    };
  }, [server, token, key]);
  // A ticket for another server or token reads as still loading.
  return issued?.key === key ? issued.ticket : null;
}
