export const MEMORY_TABS = ["timeline", "sessions", "facts", "tasks"] as const;

export type MemoryTab = (typeof MEMORY_TABS)[number];
