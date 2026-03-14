"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ClientMessage, ServerMessage } from "@/lib/types";

type Status = "disconnected" | "connecting" | "connected";

const RECONNECT_DELAYS = [500, 1000, 2000, 4000];

export function useWebSocket(
  url: string | null,
  onMessage: (msg: ServerMessage) => void,
  onDisconnect?: () => void,
) {
  const [status, setStatus] = useState<Status>("disconnected");
  const wsRef = useRef<WebSocket | null>(null);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;
  const onDisconnectRef = useRef(onDisconnect);
  onDisconnectRef.current = onDisconnect;
  const retriesRef = useRef(0);
  const unmountedRef = useRef(false);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    if (!url || unmountedRef.current) return;

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
      setStatus("connected");
      retriesRef.current = 0;
    };

    ws.onclose = () => {
      // Ignore if a newer connection already replaced this one
      if (wsRef.current !== ws) return;
      wsRef.current = null;
      setStatus("disconnected");
      onDisconnectRef.current?.();

      if (unmountedRef.current) return;
      const delay =
        RECONNECT_DELAYS[
          Math.min(retriesRef.current, RECONNECT_DELAYS.length - 1)
        ];
      retriesRef.current++;
      reconnectTimerRef.current = setTimeout(() => {
        reconnectTimerRef.current = null;
        if (!unmountedRef.current) connect();
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

  useEffect(() => {
    unmountedRef.current = false;
    retriesRef.current = 0;
    connect();

    return () => {
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
