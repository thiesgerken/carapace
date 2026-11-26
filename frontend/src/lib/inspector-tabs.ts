export const INSPECTOR_TABS = ["session", "usage", "environment", "content"] as const;

export type InspectorTab = (typeof INSPECTOR_TABS)[number];

export function isInspectorTab(value: string | null): value is InspectorTab {
  return INSPECTOR_TABS.some((tab) => tab === value);
}
