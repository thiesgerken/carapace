export const SETTINGS_TABS = [
  "preferences",
  "account",
  "prompts",
  "jobs",
  "api-keys",
  "platform-models",
  "platform-users",
] as const;

export type SettingsTab = (typeof SETTINGS_TABS)[number];

export const ADMIN_SETTINGS_TABS: readonly SettingsTab[] = ["platform-models", "platform-users"];

export function isSettingsTab(value: string): value is SettingsTab {
  return (SETTINGS_TABS as readonly string[]).includes(value);
}
