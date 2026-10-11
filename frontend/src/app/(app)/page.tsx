"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useAppShell } from "@/components/app-shell-context";
import { useBrand } from "@/hooks/use-brand";
import { ChatView } from "@/components/chat-view";
import { HomeView } from "@/components/home-view";
import type { NewSessionOptions } from "@/components/new-session-button";
import type { SessionInfo } from "@/lib/types";

const MAX_DOCUMENT_TITLE_LENGTH = 30;

export default function ChatPage() {
  const t = useTranslations();
  const shell = useAppShell();
  const { name: brand } = useBrand();
  const { activeSessionId, activeSession } = shell;
  // A session started from the home composer, waiting for its chat view to send the first message.
  const [pendingStart, setPendingStart] = useState<{ sessionId: string; content: string } | null>(null);

  const onStart = useCallback(async (content: string, options: NewSessionOptions) => {
    const session = await shell.onNewSession(options);
    if (session === null) return false;
    setPendingStart({ sessionId: session.session_id, content });
    return true;
  }, [shell]);

  const onActiveTitleUpdate = useCallback((title: string) => {
    if (!activeSessionId) return;
    shell.onTitleUpdate(activeSessionId, title);
  }, [activeSessionId, shell]);

  const onActiveSandboxUpdate = useCallback((sandbox: SessionInfo["sandbox"]) => {
    if (!activeSessionId) return;
    shell.onSandboxUpdate(activeSessionId, sandbox);
  }, [activeSessionId, shell]);

  const onActiveDelete = useCallback(async () => {
    if (!activeSessionId) return;
    await shell.onDeleteSession(activeSessionId);
  }, [activeSessionId, shell]);

  useEffect(() => {
    const sessionTitle = activeSession?.title?.trim();
    const useDefaultTitle = !activeSession || activeSession.attributes.private || !sessionTitle;
    const truncatedTitle = sessionTitle && sessionTitle.length > MAX_DOCUMENT_TITLE_LENGTH
      ? `${sessionTitle.slice(0, MAX_DOCUMENT_TITLE_LENGTH - 3)}...`
      : sessionTitle;
    document.title = useDefaultTitle ? brand : `${truncatedTitle} • ${brand}`;
  }, [activeSession, brand]);

  if (activeSessionId) {
    return (
      <ChatView
        // Remount per session: the composer reads its draft once, on mount.
        key={activeSessionId}
        server={shell.server}
        token={shell.token}
        sessionId={activeSessionId}
        session={activeSession}
        initialSandbox={activeSession?.sandbox ?? null}
        onTitleUpdate={onActiveTitleUpdate}
        onSessionUpdate={shell.onSessionUpdate}
        onSandboxUpdate={onActiveSandboxUpdate}
        onForkSession={shell.onForkSession}
        onOpenJobSettings={shell.onOpenJobSettings}
        onUpdateSessionAttributes={shell.onUpdateSessionAttributes}
        onDeleteSession={onActiveDelete}
        initialMessage={pendingStart?.sessionId === activeSessionId ? pendingStart.content : undefined}
        onInitialMessageSent={() => setPendingStart(null)}
      />
    );
  }

  return (
    <HomeView
      server={shell.server}
      agentName={shell.currentUser?.agentName?.trim() || t("app.name")}
      onStart={onStart}
    />
  );
}
