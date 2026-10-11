import { MemoryTabPanel } from "@/components/memory-tab-panel";
import { MEMORY_TABS, type MemoryTab } from "@/lib/memory-tabs";

export const dynamicParams = false;

export function generateStaticParams() {
  return MEMORY_TABS.map((tab) => ({ tab }));
}

export default async function MemoryTabPage({ params }: { params: Promise<{ tab: string }> }) {
  const { tab } = await params;
  return <MemoryTabPanel tab={tab as MemoryTab} />;
}
