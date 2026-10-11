"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAppShell } from "@/components/app-shell-context";
import { AdminUsersPage } from "@/components/admin-users-page";
import { ApiKeysView } from "@/components/api-keys-view";
import { JobsView } from "@/components/jobs-view";
import { PlatformSettingsView } from "@/components/platform-settings-view";
import { PreferencesView } from "@/components/preferences-view";
import { PromptPreviewView } from "@/components/prompt-preview-view";
import { UserSettingsView } from "@/components/user-settings-view";
import { ADMIN_SETTINGS_TABS, type SettingsTab } from "@/lib/settings-tabs";

const panelClassName = "flex min-h-0 flex-1 flex-col overflow-clip bg-background/65";

export function SettingsTabPanel({ tab }: { tab: SettingsTab }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const shell = useAppShell();
  const { isAdmin, currentUser } = shell;

  const adminOnly = ADMIN_SETTINGS_TABS.includes(tab);
  // currentUser loads asynchronously on a stored connection; isAdmin is false until it resolves.
  // Only bounce once we actually know the user is a non-admin, else an admin deep-linking a
  // platform tab gets redirected before their roles are known.
  const denied = adminOnly && currentUser !== null && !isAdmin;

  useEffect(() => {
    if (denied) {
      router.replace("/settings/preferences");
    }
  }, [denied, router]);

  if (adminOnly && !isAdmin) {
    return null;
  }

  switch (tab) {
    case "account":
      return (
        <div id="settings-panel-account" role="tabpanel" aria-labelledby="settings-tab-account" className={panelClassName}>
          <UserSettingsView server={shell.server} token={shell.token} />
        </div>
      );
    case "prompts":
      return (
        <div id="settings-panel-prompts" role="tabpanel" aria-labelledby="settings-tab-prompts" className={panelClassName}>
          <PromptPreviewView server={shell.server} />
        </div>
      );
    case "jobs":
      return (
        <div
          id="settings-panel-jobs"
          role="tabpanel"
          aria-labelledby="settings-tab-jobs"
          className="grid min-h-0 flex-1 gap-0 lg:grid-cols-[22rem_minmax(0,1fr)]"
        >
          <JobsView
            server={shell.server}
            token={shell.token}
            sessions={shell.sessions}
            requestedJobId={searchParams.get("job")}
            onSessionActivated={shell.onForkSession}
          />
        </div>
      );
    case "api-keys":
      return (
        <div id="settings-panel-api-keys" role="tabpanel" aria-labelledby="settings-tab-api-keys" className={panelClassName}>
          <ApiKeysView server={shell.server} token={shell.token} isAdmin={isAdmin} />
        </div>
      );
    case "platform-models":
      return (
        <div id="settings-panel-platform-models" role="tabpanel" aria-labelledby="settings-tab-platform-models" className={panelClassName}>
          <PlatformSettingsView server={shell.server} token={shell.token} />
        </div>
      );
    case "platform-users":
      return (
        <div id="settings-panel-platform-users" role="tabpanel" aria-labelledby="settings-tab-platform-users" className={panelClassName}>
          <AdminUsersPage key={shell.server} embedded server={shell.server} currentUsername={shell.currentUser?.username ?? null} />
        </div>
      );
    default:
      return (
        <div id="settings-panel-preferences" role="tabpanel" aria-labelledby="settings-tab-preferences" className={panelClassName}>
          <PreferencesView
            embedded
            server={shell.server}
            token={shell.token}
            showArchivedSessions={shell.showArchivedSessions}
            onShowArchivedSessionsChange={shell.onShowArchivedSessionsChange}
          />
        </div>
      );
  }
}
