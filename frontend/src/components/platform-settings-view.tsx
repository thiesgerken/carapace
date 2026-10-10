"use client";

import { Ban, Brain, BrainCircuit, Check, ChevronDown, Cloud, Copy, Eye, KeyRound, Loader2, Plus, Save, StretchHorizontal, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { type ComponentType, useCallback, useEffect, useId, useMemo, useRef, useState } from "react";

import {
  getPlatformSettings,
  updatePlatformSettings,
  type AvailableModelInfo,
  type PlatformDefaultModelsSettings,
  type PlatformModelEntryInfo,
  type PlatformModelEntryPatchInput,
  type PlatformSettingsPatchInput,
  type PlatformSettingsResponseInfo,
  type SessionBudgetSettings,
} from "@/lib/api";
import { ModelPicker, withSelectedModelOption } from "@/components/model-picker";
import { cn } from "@/lib/utils";

type SecretSource = "none" | "raw" | "env" | "file";
type ThinkingDraft = "" | "true" | "false" | "minimal" | "low" | "medium" | "high" | "xhigh";

interface ModelDraft {
  rowId: string;
  provider: string;
  name: string;
  id: string;
  maxInputTokens: string;
  thinking: ThinkingDraft;
  thinkingBudgetTokens: string;
  baseUrl: string;
  vision: boolean;
  enabled: boolean;
  apiKeySource: SecretSource;
  apiKeyValue: string;
  apiKeyConfigured: boolean;
  apiKeyConfiguredSource: SecretSource;
}

interface PlatformDraft {
  // Keeps every stored default model so the ones this view does not edit pass through on save.
  defaultModels: Omit<PlatformDefaultModelsSettings, "compaction"> & { compaction: string };
  budget: Record<keyof Required<SessionBudgetSettings>, string>;
  compaction: {
    keepTurns: string;
    verbatimTurns: string;
    toolFloor: string;
  };
  models: ModelDraft[];
}

type Translate = (key: string, values?: Record<string, string | number>) => string;
type BadgeIcon = ComponentType<{ className?: string }>;

interface SummaryBadge {
  label: string;
  className: string;
  icon?: BadgeIcon;
}

const providerPresets = ["anthropic", "google-gla", "google-vertex", "openai", "openai-chat", "openai-codex", "openrouter"];
const thinkingOptions: ThinkingDraft[] = ["", "true", "false", "minimal", "low", "medium", "high", "xhigh"];

const inputClassName = cn(
  "w-full rounded-xl border border-border bg-background px-3 py-2.5 text-sm",
  "outline-none transition-colors placeholder:text-muted-foreground/50",
  "focus:border-ring focus:ring-2 focus:ring-ring/30",
);
const disabledBadgeClassName = "rounded-md border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-200";
const neutralBadgeClassName = "rounded-md border border-border bg-muted/50 px-2 py-0.5 text-xs text-muted-foreground";
const providerBadgeClassNames = [
  "rounded-md border border-sky-200 bg-sky-50 px-2 py-0.5 text-xs text-sky-800 dark:border-sky-900/60 dark:bg-sky-950/40 dark:text-sky-200",
  "rounded-md border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-xs text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-200",
  "rounded-md border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-200",
  "rounded-md border border-rose-200 bg-rose-50 px-2 py-0.5 text-xs text-rose-800 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-200",
  "rounded-md border border-violet-200 bg-violet-50 px-2 py-0.5 text-xs text-violet-800 dark:border-violet-900/60 dark:bg-violet-950/40 dark:text-violet-200",
  "rounded-md border border-cyan-200 bg-cyan-50 px-2 py-0.5 text-xs text-cyan-800 dark:border-cyan-900/60 dark:bg-cyan-950/40 dark:text-cyan-200",
];
const modelBadgeClassNames = [
  "rounded-md border border-lime-200 bg-lime-50 px-2 py-0.5 text-xs text-lime-800 dark:border-lime-900/60 dark:bg-lime-950/40 dark:text-lime-200",
  "rounded-md border border-fuchsia-200 bg-fuchsia-50 px-2 py-0.5 text-xs text-fuchsia-800 dark:border-fuchsia-900/60 dark:bg-fuchsia-950/40 dark:text-fuchsia-200",
  "rounded-md border border-teal-200 bg-teal-50 px-2 py-0.5 text-xs text-teal-800 dark:border-teal-900/60 dark:bg-teal-950/40 dark:text-teal-200",
  "rounded-md border border-orange-200 bg-orange-50 px-2 py-0.5 text-xs text-orange-800 dark:border-orange-900/60 dark:bg-orange-950/40 dark:text-orange-200",
  "rounded-md border border-indigo-200 bg-indigo-50 px-2 py-0.5 text-xs text-indigo-800 dark:border-indigo-900/60 dark:bg-indigo-950/40 dark:text-indigo-200",
  "rounded-md border border-pink-200 bg-pink-50 px-2 py-0.5 text-xs text-pink-800 dark:border-pink-900/60 dark:bg-pink-950/40 dark:text-pink-200",
];

let modelDraftId = 0;

function nextModelDraftId(): string {
  modelDraftId += 1;
  return `platform-model-${modelDraftId}`;
}

function baseUrlHost(baseUrl: string): string {
  const trimmed = baseUrl.trim();
  if (!trimmed) return "";
  try {
    return new URL(trimmed).hostname;
  } catch {
    try {
      return new URL(`http://${trimmed}`).hostname;
    } catch {
      return "";
    }
  }
}

function providerKey(provider: string, baseUrl: string): string {
  const providerName = provider.trim().toLowerCase();
  const host = baseUrlHost(baseUrl).toLowerCase();
  return host ? `${providerName}@${host}` : providerName;
}

function providerBadgeLabel(provider: string, baseUrl: string): string {
  const providerName = provider.trim();
  const host = baseUrlHost(baseUrl);
  return host ? `${providerName} @ ${host}` : providerName;
}

function modelNameKey(name: string): string {
  return name.trim().toLowerCase();
}

function badgeClassNameFromHash(key: string, classNames: readonly string[]): string {
  let hash = 0;
  for (let index = 0; index < key.length; index += 1) {
    hash = (hash * 31 + key.charCodeAt(index)) >>> 0;
  }
  return classNames[hash % classNames.length];
}

function providerBadgeClassName(provider: string, baseUrl: string): string {
  const normalized = providerKey(provider, baseUrl);
  if (!normalized) return neutralBadgeClassName;
  return badgeClassNameFromHash(normalized, providerBadgeClassNames);
}

function modelNameBadgeClassName(name: string): string {
  const normalized = modelNameKey(name);
  if (!normalized) return neutralBadgeClassName;
  return badgeClassNameFromHash(normalized, modelBadgeClassNames);
}

function compactTokenCount(value: string): string {
  const normalized = value.trim().replaceAll(",", "").replaceAll("_", "");
  const parsed = Number(normalized);
  if (!Number.isFinite(parsed) || parsed <= 0) return value.trim();
  if (parsed < 1_000) return String(parsed);
  const compact = parsed / 1_000;
  return `${Number.isInteger(compact) ? compact.toFixed(0) : compact.toFixed(1)}k`;
}

function tokenLabel(value: string, t: Translate): string {
  return `${value} ${t("units.tokens")}`;
}

function thinkingBadgeLabel(thinking: ThinkingDraft, thinkingBudgetTokens: string, t: Translate): string {
  if (thinkingBudgetTokens.trim() === "0") return t("thinking.false");
  const budget = thinkingBudgetTokens.trim();
  if (!thinking) return tokenLabel(budget, t);
  const label = t(`thinking.${thinking}`);
  return budget ? `${label}: ${tokenLabel(budget, t)}` : label;
}

function modelId(model: Pick<ModelDraft, "provider" | "name" | "id">): string {
  return model.id.trim() || `${model.provider.trim()}:${model.name.trim()}`;
}

function compareModelText(left: string, right: string): number {
  return left.localeCompare(right, undefined, { sensitivity: "base" });
}

function isIncompleteModelDraft(model: Pick<ModelDraft, "provider" | "name">): boolean {
  return !model.provider.trim() || !model.name.trim();
}

export function sortModelDrafts(models: ModelDraft[]): ModelDraft[] {
  return [...models].sort((left, right) => {
    const leftIncomplete = isIncompleteModelDraft(left);
    const rightIncomplete = isIncompleteModelDraft(right);
    if (leftIncomplete !== rightIncomplete) {
      return leftIncomplete ? -1 : 1;
    }
    if (leftIncomplete && rightIncomplete) {
      return 0;
    }

    const providerOrder = compareModelText(left.provider.trim(), right.provider.trim());
    if (providerOrder !== 0) return providerOrder;

    const nameOrder = compareModelText(left.name.trim(), right.name.trim());
    if (nameOrder !== 0) return nameOrder;

    return compareModelText(modelId(left), modelId(right));
  });
}

function isOpenAICompatibleProvider(provider: string): boolean {
  const normalized = provider.trim().toLowerCase();
  return normalized === "openai" || normalized === "openai-chat";
}

function supportsModelApiKey(provider: string): boolean {
  const normalized = provider.trim().toLowerCase();
  return isOpenAICompatibleProvider(normalized) || normalized === "openrouter";
}

function hasReusableRawSecret(model: Pick<ModelDraft, "apiKeyConfigured" | "apiKeyConfiguredSource">): boolean {
  return model.apiKeyConfigured && model.apiKeyConfiguredSource === "raw";
}

function apiKeySourceChangePatch(model: ModelDraft, apiKeySource: SecretSource): Partial<ModelDraft> {
  return {
    apiKeySource,
    apiKeyValue: "",
    apiKeyConfigured: model.apiKeyConfigured,
    apiKeyConfiguredSource: model.apiKeyConfiguredSource,
  };
}

function budgetDraftFromSettings(budget: SessionBudgetSettings): PlatformDraft["budget"] {
  return {
    input_tokens: budget.input_tokens?.toString() ?? "",
    output_tokens: budget.output_tokens?.toString() ?? "",
    cost_usd: budgetCostValue(budget.cost_usd),
    tool_calls: budget.tool_calls?.toString() ?? "",
  };
}

function modelDraftFromSettings(model: PlatformModelEntryInfo): ModelDraft {
  const apiKeySource = model.api_key.source ?? "none";
  return {
    rowId: nextModelDraftId(),
    provider: model.provider,
    name: model.name,
    id: model.id === `${model.provider}:${model.name}` ? "" : model.id,
    maxInputTokens: model.max_input_tokens?.toString() ?? "",
    thinking: model.thinking === true ? "true" : model.thinking === false ? "false" : model.thinking ?? "",
    thinkingBudgetTokens: model.thinking_budget_tokens?.toString() ?? "",
    baseUrl: model.base_url ?? "",
    vision: model.vision ?? false,
    enabled: model.enabled,
    apiKeySource,
    apiKeyValue: apiKeySource === "raw" ? "" : model.api_key.value ?? "",
    apiKeyConfigured: model.api_key.configured,
    apiKeyConfiguredSource: model.api_key.configured ? apiKeySource : "none",
  };
}

function draftFromSettings(response: PlatformSettingsResponseInfo): PlatformDraft {
  const { default_models, compaction } = response.settings;
  return {
    defaultModels: { ...default_models, compaction: default_models.compaction ?? "" },
    budget: budgetDraftFromSettings(response.settings.default_budget),
    compaction: {
      keepTurns: String(compaction.keep_turns),
      verbatimTurns: String(compaction.verbatim_tool_turns),
      toolFloor: String(compaction.tool_output_floor_tokens),
    },
    models: sortModelDrafts(response.settings.available_models.map(modelDraftFromSettings)),
  };
}

function numericLimit(value: string, field: string, t: Translate): number | null {
  const normalized = value.trim();
  if (!normalized) return null;
  if (!/^\d+$/.test(normalized)) {
    throw new Error(t("errors.wholeNumber", { field }));
  }
  const parsed = Number(normalized);
  return parsed > 0 ? parsed : null;
}

function nonNegativeLimit(value: string, field: string, t: Translate): number | null {
  const normalized = value.trim();
  if (!normalized) return null;
  if (!/^\d+$/.test(normalized)) {
    throw new Error(t("errors.nonNegativeWholeNumber", { field }));
  }
  return Number(normalized);
}

function budgetCostValue(value: number | string | null | undefined): string {
  const trimmed = value === null || value === undefined ? "" : String(value).trim();
  if (!trimmed) return "";
  const normalized = trimmed.replace(",", ".");
  const parsed = Number(normalized);
  if (parsed === 0) return "";
  if (!Number.isFinite(parsed)) return trimmed;
  return parsed.toFixed(2);
}

function budgetFromDraft(draft: PlatformDraft, t: Translate): SessionBudgetSettings {
  const cost = draft.budget.cost_usd.trim().replace(",", ".");
  if (cost && (!/^\d+(\.\d+)?$/.test(cost) || Number(cost) < 0)) {
    throw new Error(t("errors.number", { field: t("fields.costUsd") }));
  }
  return {
    input_tokens: numericLimit(draft.budget.input_tokens, t("fields.inputTokens"), t),
    output_tokens: numericLimit(draft.budget.output_tokens, t("fields.outputTokens"), t),
    cost_usd: cost ? budgetCostValue(cost) || null : null,
    tool_calls: numericLimit(draft.budget.tool_calls, t("fields.toolCalls"), t),
  };
}

function thinkingFromDraft(value: ThinkingDraft): PlatformModelEntryPatchInput["thinking"] {
  if (!value) return null;
  if (value === "true") return true;
  if (value === "false") return false;
  return value;
}

function modelsFromDraft(models: ModelDraft[], t: Translate): PlatformModelEntryPatchInput[] {
  const ids = new Set<string>();
  return models.map((model, index) => {
    const provider = model.provider.trim();
    const name = model.name.trim();
    const id = model.id.trim() || null;
    if (!provider) throw new Error(t("errors.providerRequired", { index: index + 1 }));
    if (!name) throw new Error(t("errors.nameRequired", { index: index + 1 }));
    const effectiveId = id ?? `${provider}:${name}`;
    if (ids.has(effectiveId)) throw new Error(t("errors.duplicateModel", { id: effectiveId }));
    ids.add(effectiveId);
    const openAICompatible = isOpenAICompatibleProvider(provider);
    const modelApiKeySupported = supportsModelApiKey(provider);
    if (modelApiKeySupported && model.apiKeySource === "raw" && !model.apiKeyValue.trim() && !hasReusableRawSecret(model)) {
      throw new Error(t("errors.rawSecretRequired", { id: effectiveId }));
    }
    if (modelApiKeySupported && (model.apiKeySource === "env" || model.apiKeySource === "file") && !model.apiKeyValue.trim()) {
      throw new Error(t("errors.secretValueRequired", { id: effectiveId }));
    }

    const entry: PlatformModelEntryPatchInput = {
      provider,
      name,
      id,
      max_input_tokens: numericLimit(model.maxInputTokens, t("fields.maxInputTokens"), t),
      thinking: thinkingFromDraft(model.thinking),
      vision: model.vision,
      enabled: model.enabled,
    };
    if (openAICompatible) {
      entry.thinking_budget_tokens = nonNegativeLimit(model.thinkingBudgetTokens, t("fields.thinkingBudgetTokens"), t);
      entry.base_url = model.baseUrl.trim() || null;
    }
    if (modelApiKeySupported) {
      entry.api_key = model.apiKeySource === "none"
        ? { source: null }
        : {
            source: model.apiKeySource,
            ...(model.apiKeyValue.trim() ? { value: model.apiKeyValue.trim() } : {}),
          };
    }
    return entry;
  });
}

export function buildPlatformSettingsPatch(draft: PlatformDraft, t: Translate): PlatformSettingsPatchInput {
  const availableModels = modelsFromDraft(draft.models, t);
  const byId = new Map(availableModels.map((model) => [model.id ?? `${model.provider}:${model.name}`, model]));
  const checkDefault = (field: string, id: string) => {
    const entry = byId.get(id);
    if (entry === undefined) throw new Error(t("errors.defaultUnknown", { field, id }));
    if (entry.enabled === false) throw new Error(t("errors.defaultDisabled", { field, id }));
  };
  for (const key of ["agent", "sentinel", "title"] as const) {
    const normalized = draft.defaultModels[key].trim();
    if (!normalized) throw new Error(t("errors.defaultRequired", { field: t(`fields.${key}`) }));
    checkDefault(t(`fields.${key}`), normalized);
  }
  const compactionModel = draft.defaultModels.compaction.trim();
  if (compactionModel) checkDefault(t("fields.compaction"), compactionModel);
  return {
    default_models: {
      ...draft.defaultModels,
      agent: draft.defaultModels.agent.trim(),
      sentinel: draft.defaultModels.sentinel.trim(),
      title: draft.defaultModels.title.trim(),
      compaction: compactionModel || null,
    },
    default_budget: budgetFromDraft(draft, t),
    compaction: {
      keep_turns: boundedInt(draft.compaction.keepTurns, t("compaction.keepTurns"), 1, t),
      verbatim_tool_turns: boundedInt(draft.compaction.verbatimTurns, t("compaction.verbatimTurns"), 0, t),
      tool_output_floor_tokens: boundedInt(draft.compaction.toolFloor, t("compaction.toolFloor"), 1, t),
    },
    available_models: availableModels,
  };
}

function boundedInt(value: string, field: string, min: number, t: Translate): number {
  const normalized = value.trim();
  if (!/^\d+$/.test(normalized) || Number(normalized) < min) {
    throw new Error(t("errors.minInt", { field, min }));
  }
  return Number(normalized);
}

function comparableDraft(draft: PlatformDraft | null): unknown {
  if (!draft) return null;
  return {
    defaultModels: draft.defaultModels,
    budget: draft.budget,
    compaction: draft.compaction,
    models: draft.models.map((model) => ({
      provider: model.provider,
      name: model.name,
      id: model.id,
      maxInputTokens: model.maxInputTokens,
      thinking: model.thinking,
      thinkingBudgetTokens: model.thinkingBudgetTokens,
      baseUrl: model.baseUrl,
      vision: model.vision,
      enabled: model.enabled,
      apiKeySource: model.apiKeySource,
      apiKeyValue: model.apiKeyValue,
      apiKeyConfigured: model.apiKeyConfigured,
      apiKeyConfiguredSource: model.apiKeyConfiguredSource,
    })),
  };
}

function draftModelOptions(models: ModelDraft[]): AvailableModelInfo[] {
  return sortModelDrafts(models)
    .filter((model) => model.enabled && model.provider.trim() && model.name.trim())
    .map((model) => ({
      id: modelId(model),
      provider: model.provider.trim(),
      name: model.name.trim(),
      max_input_tokens: Number(model.maxInputTokens) || null,
    }));
}

function newModelDraft(): ModelDraft {
  return {
    rowId: nextModelDraftId(),
    provider: "openai",
    name: "",
    id: "",
    maxInputTokens: "",
    thinking: "",
    thinkingBudgetTokens: "",
    baseUrl: "",
    vision: false,
    enabled: true,
    apiKeySource: "none",
    apiKeyValue: "",
    apiKeyConfigured: false,
    apiKeyConfiguredSource: "none",
  };
}

// ponytail: everything but the stored secret is copied; the suffixed name/id keep the duplicate from colliding.
function copyModelDraft(model: ModelDraft, t: Translate): ModelDraft {
  const suffix = t("actions.copySuffix");
  return {
    ...model,
    rowId: nextModelDraftId(),
    name: `${model.name} ${suffix}`,
    id: model.id.trim() ? `${model.id} ${suffix}` : "",
    apiKeyValue: "",
    apiKeyConfigured: false,
    apiKeyConfiguredSource: "none",
  };
}

export function PlatformSettingsView({ server, token }: { server: string; token: string }) {
  const t = useTranslations("platformSettings");
  const [settings, setSettings] = useState<PlatformSettingsResponseInfo | null>(null);
  const [draft, setDraft] = useState<PlatformDraft | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [copiedRowIds, setCopiedRowIds] = useState<Set<string>>(new Set());

  const loadSettings = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await getPlatformSettings(server, token);
      setSettings(response);
      setDraft(draftFromSettings(response));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : t("errors.load"));
    } finally {
      setLoading(false);
    }
  }, [server, t, token]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadSettings(), 0);
    return () => window.clearTimeout(timer);
  }, [loadSettings]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 30_000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const modelOptions = useMemo(() => draftModelOptions(draft?.models ?? []), [draft?.models]);
  const changed = useMemo(() => comparableDraft(draft) !== null && JSON.stringify(comparableDraft(draft)) !== JSON.stringify(comparableDraft(settings ? draftFromSettings(settings) : null)), [draft, settings]);
  const configWritable = settings?.config_writable ?? false;
  const fieldsDisabled = saving || !configWritable;
  const agentOptions = useMemo(() => withSelectedModelOption(modelOptions, draft?.defaultModels.agent), [draft?.defaultModels.agent, modelOptions]);
  const sentinelOptions = useMemo(() => withSelectedModelOption(modelOptions, draft?.defaultModels.sentinel), [draft?.defaultModels.sentinel, modelOptions]);
  const titleOptions = useMemo(() => withSelectedModelOption(modelOptions, draft?.defaultModels.title), [draft?.defaultModels.title, modelOptions]);
  const compactionOptions = useMemo(() => withSelectedModelOption(modelOptions, draft?.defaultModels.compaction), [draft?.defaultModels.compaction, modelOptions]);

  function updateDraft(patch: Partial<PlatformDraft>): void {
    setNotice(null);
    setDraft((current) => current ? { ...current, ...patch } : current);
  }

  function updateModel(rowId: string, patch: Partial<ModelDraft>): void {
    setNotice(null);
    setDraft((current) => current ? {
      ...current,
      models: current.models.map((model) => model.rowId === rowId ? { ...model, ...patch } : model),
    } : current);
  }

  async function handleSave(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!draft || !changed || !configWritable) return;
    let body: PlatformSettingsPatchInput;
    try {
      body = buildPlatformSettingsPatch(draft, t);
    } catch (buildError) {
      setError(buildError instanceof Error ? buildError.message : t("errors.save"));
      setNotice(null);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const response = await updatePlatformSettings(server, token, body);
      setSettings(response);
      setDraft(draftFromSettings(response));
      setNotice(t("notices.saved"));
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : t("errors.save"));
      setNotice(null);
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <div className="flex min-h-0 flex-1 items-center justify-center text-sm text-muted-foreground"><Loader2 className="mr-2 h-4 w-4 animate-spin" />{t("status.loading")}</div>;
  }

  if (!draft || !settings) {
    return <div className="flex min-h-0 flex-1 items-center justify-center px-6 text-sm text-destructive">{error ?? t("status.unavailable")}</div>;
  }

  return (
    <form onSubmit={(event) => void handleSave(event)} className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-6">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 space-y-1">
            <div className={cn("min-h-5 text-sm", error ? "text-destructive" : "text-muted-foreground")}>
              {error ? error : notice ? <span className="inline-flex items-center gap-2"><Check className="h-4 w-4" />{notice}</span> : configWritable ? null : t("status.readOnly")}
            </div>
          </div>
          <button
            type="submit"
            disabled={saving || !changed || !configWritable}
            className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-background transition-colors hover:bg-foreground/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            {saving ? t("actions.saving") : t("actions.save")}
          </button>
        </div>

        <Section title={t("sections.defaultModels")}>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Field label={t("fields.agent")}>
              <ModelPicker value={draft.defaultModels.agent} entries={agentOptions} onChange={(agent) => updateDraft({ defaultModels: { ...draft.defaultModels, agent: agent ?? "" } })} disabled={fieldsDisabled} defaultLabel={t("placeholders.selectModel")} />
            </Field>
            <Field label={t("fields.sentinel")}>
              <ModelPicker value={draft.defaultModels.sentinel} entries={sentinelOptions} onChange={(sentinel) => updateDraft({ defaultModels: { ...draft.defaultModels, sentinel: sentinel ?? "" } })} disabled={fieldsDisabled} defaultLabel={t("placeholders.selectModel")} />
            </Field>
            <Field label={t("fields.title")}>
              <ModelPicker value={draft.defaultModels.title} entries={titleOptions} onChange={(title) => updateDraft({ defaultModels: { ...draft.defaultModels, title: title ?? "" } })} disabled={fieldsDisabled} defaultLabel={t("placeholders.selectModel")} />
            </Field>
            <Field label={t("fields.compaction")}>
              <ModelPicker value={draft.defaultModels.compaction} entries={compactionOptions} onChange={(model) => updateDraft({ defaultModels: { ...draft.defaultModels, compaction: model ?? "" } })} disabled={fieldsDisabled} defaultLabel={t("compaction.modelDefault")} />
            </Field>
          </div>
        </Section>

        <Section title={t("sections.defaultBudgets")}>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <TextInput label={t("fields.inputTokens")} value={draft.budget.input_tokens} disabled={fieldsDisabled} placeholder={t("placeholders.unlimited")} onChange={(value) => updateDraft({ budget: { ...draft.budget, input_tokens: value } })} />
            <TextInput label={t("fields.outputTokens")} value={draft.budget.output_tokens} disabled={fieldsDisabled} placeholder={t("placeholders.unlimited")} onChange={(value) => updateDraft({ budget: { ...draft.budget, output_tokens: value } })} />
            <TextInput label={t("fields.costUsd")} value={draft.budget.cost_usd} disabled={fieldsDisabled} placeholder={t("placeholders.unlimited")} onBlur={() => updateDraft({ budget: { ...draft.budget, cost_usd: budgetCostValue(draft.budget.cost_usd) } })} onChange={(value) => updateDraft({ budget: { ...draft.budget, cost_usd: value } })} />
            <TextInput label={t("fields.toolCalls")} value={draft.budget.tool_calls} disabled={fieldsDisabled} placeholder={t("placeholders.unlimited")} onChange={(value) => updateDraft({ budget: { ...draft.budget, tool_calls: value } })} />
          </div>
        </Section>

        <Section title={t("sections.compaction")}>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <TextInput label={t("compaction.keepTurns")} value={draft.compaction.keepTurns} disabled={fieldsDisabled} onChange={(value) => updateDraft({ compaction: { ...draft.compaction, keepTurns: value } })} />
            <TextInput label={t("compaction.verbatimTurns")} value={draft.compaction.verbatimTurns} disabled={fieldsDisabled} onChange={(value) => updateDraft({ compaction: { ...draft.compaction, verbatimTurns: value } })} />
            <TextInput label={t("compaction.toolFloor")} value={draft.compaction.toolFloor} disabled={fieldsDisabled} onChange={(value) => updateDraft({ compaction: { ...draft.compaction, toolFloor: value } })} />
          </div>
        </Section>

        <Section
          title={t("sections.catalog")}
          action={(
            <SecondaryButton disabled={fieldsDisabled} onClick={() => updateDraft({ models: [newModelDraft(), ...draft.models] })}>
              <Plus className="h-4 w-4" />
              {t("actions.addModel")}
            </SecondaryButton>
          )}
        >
          <div className="space-y-3">
            {draft.models.map((model) => (
              <ModelRow
                key={model.rowId}
                model={model}
                disabled={fieldsDisabled}
                defaultOpen={copiedRowIds.has(model.rowId)}
                onChange={(patch) => updateModel(model.rowId, patch)}
                onRemove={() => updateDraft({ models: draft.models.filter((item) => item.rowId !== model.rowId) })}
                onCopy={() => {
                  const copy = copyModelDraft(model, t);
                  setCopiedRowIds((previous) => new Set(previous).add(copy.rowId));
                  updateDraft({ models: [copy, ...draft.models] });
                }}
                t={t}
              />
            ))}
          </div>
        </Section>
      </div>
    </form>
  );
}

function Section({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-border bg-background/88 p-4 shadow-sm sm:p-5">
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-muted-foreground">{title}</h2>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      {children}
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

function TextInput({ label, value, onChange, placeholder, onBlur, disabled = false }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string; onBlur?: () => void; disabled?: boolean }) {
  return (
    <Field label={label}>
      <input type="text" value={value} disabled={disabled} placeholder={placeholder} onBlur={onBlur} onChange={(event) => onChange(event.target.value)} className={inputClassName} />
    </Field>
  );
}

function SecondaryButton({ children, disabled, onClick }: { children: React.ReactNode; disabled?: boolean; onClick: () => void }) {
  return (
    <button type="button" disabled={disabled} onClick={onClick} className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-border bg-background px-3 py-2 text-sm font-medium transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50">
      {children}
    </button>
  );
}

function ProviderInput({ value, disabled, onChange }: { value: string; disabled: boolean; onChange: (value: string) => void }) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);

  function closeWhenFocusLeaves(event: React.FocusEvent<HTMLDivElement>): void {
    const nextTarget = event.relatedTarget;
    if (nextTarget instanceof Node && wrapperRef.current?.contains(nextTarget)) return;
    setOpen(false);
  }

  function toggleDropdown(): void {
    if (disabled) return;
    setOpen((current) => !current);
    window.setTimeout(() => inputRef.current?.focus(), 0);
  }

  return (
    <div ref={wrapperRef} className="relative" onBlur={closeWhenFocusLeaves}>
      <input
        ref={inputRef}
        type="text"
        value={value}
        disabled={disabled}
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-haspopup="listbox"
        aria-autocomplete="list"
        onFocus={() => setOpen(true)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") setOpen(true);
          if (event.key === "Escape") setOpen(false);
        }}
        onChange={(event) => onChange(event.target.value)}
        className={cn(inputClassName, "pr-10")}
      />
      <button
        type="button"
        disabled={disabled}
        aria-label="Provider presets"
        aria-expanded={open}
        onMouseDown={(event) => event.preventDefault()}
        onClick={toggleDropdown}
        className="absolute right-1 top-1/2 inline-flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
      >
        <ChevronDown className={cn("h-4 w-4 transition-transform", open ? "rotate-180" : null)} />
      </button>
      {open ? (
        <div id={listId} role="listbox" className="absolute z-30 mt-2 max-h-56 w-full overflow-y-auto rounded-xl border border-border bg-background p-1 shadow-xl">
          {providerPresets.map((provider) => (
            <button
              key={provider}
              type="button"
              role="option"
              aria-selected={provider === value}
              className={cn(
                "block w-full rounded-lg px-2.5 py-2 text-left font-mono text-sm transition-colors focus:outline-none",
                provider === value ? "bg-accent text-accent-foreground" : "hover:bg-accent/50 focus:bg-accent/50",
              )}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => {
                onChange(provider);
                setOpen(false);
                inputRef.current?.focus();
              }}
            >
              {provider}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function ModelRow({ model, disabled, defaultOpen = false, onChange, onRemove, onCopy, t }: { model: ModelDraft; disabled: boolean; defaultOpen?: boolean; onChange: (patch: Partial<ModelDraft>) => void; onRemove: () => void; onCopy: () => void; t: Translate }) {
  const incomplete = isIncompleteModelDraft(model);
  const [expanded, setExpanded] = useState(incomplete || defaultOpen);
  const open = expanded || incomplete;
  const effectiveId = modelId(model);
  const summaryId = model.name.trim() ? effectiveId : t("placeholders.generatedId");
  const provider = model.provider.trim();
  const openAICompatible = isOpenAICompatibleProvider(provider);
  const modelApiKeySupported = supportsModelApiKey(provider);
  const openAIFieldsDisabled = disabled || !openAICompatible;
  const apiKeyFieldsDisabled = disabled || !modelApiKeySupported;
  const providerLabel = providerBadgeLabel(provider, openAICompatible ? model.baseUrl : "");
  const summaryBadges: SummaryBadge[] = [];
  if (provider) summaryBadges.push({ label: providerLabel, className: providerBadgeClassName(provider, openAICompatible ? model.baseUrl : ""), icon: Cloud });
  if (model.name.trim()) summaryBadges.push({ label: model.name.trim(), className: modelNameBadgeClassName(model.name), icon: BrainCircuit });
  if (model.maxInputTokens.trim()) summaryBadges.push({ label: tokenLabel(compactTokenCount(model.maxInputTokens), t), className: neutralBadgeClassName, icon: StretchHorizontal });
  if (model.thinking || (openAICompatible && model.thinkingBudgetTokens.trim())) summaryBadges.push({ label: thinkingBadgeLabel(model.thinking, openAICompatible ? model.thinkingBudgetTokens : "", t), className: neutralBadgeClassName, icon: Brain });
  if (model.vision) summaryBadges.push({ label: t("fields.vision"), className: neutralBadgeClassName, icon: Eye });
  if (!model.enabled) summaryBadges.push({ label: t("fields.disabled"), className: disabledBadgeClassName, icon: Ban });
  const rawSecretConfigured = model.apiKeySource === "raw" && hasReusableRawSecret(model);
  return (
    <details
      className="group rounded-lg border border-border bg-background/70"
      open={open}
      onToggle={(event) => {
        const nextOpen = event.currentTarget.open;
        if (!nextOpen && incomplete) {
          event.currentTarget.open = true;
          setExpanded(true);
          return;
        }
        setExpanded(nextOpen);
      }}
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-4 outline-none transition-colors hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring/30 [&::-webkit-details-marker]:hidden">
        <div className="min-w-0 space-y-2">
          <div className="break-all font-mono text-sm font-medium">{summaryId}</div>
          {summaryBadges.length ? (
            <div className="flex flex-wrap gap-1.5">
              {summaryBadges.map((badge) => {
                const Icon = badge.icon;
                return (
                  <span key={badge.label} className={cn(badge.className, Icon ? "inline-flex items-center gap-1" : null)}>
                    {Icon ? <Icon className="h-3 w-3" /> : null}
                    {badge.label}
                  </span>
                );
              })}
            </div>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button type="button" disabled={disabled} onClick={(event) => { event.preventDefault(); event.stopPropagation(); onCopy(); }} title={t("actions.copyModel")} aria-label={t("actions.copyModel")} className="inline-flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50">
            <Copy className="h-4 w-4" />
          </button>
          <button type="button" disabled={disabled} onClick={(event) => { event.preventDefault(); event.stopPropagation(); if (incomplete || window.confirm(t("actions.confirmRemoveModel", { name: model.name.trim() }))) onRemove(); }} title={t("actions.removeModel")} aria-label={t("actions.removeModel")} className="inline-flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-destructive disabled:cursor-not-allowed disabled:opacity-50">
            <Trash2 className="h-4 w-4" />
          </button>
          <ChevronDown className="h-4 w-4 text-muted-foreground transition-transform group-open:rotate-180" />
        </div>
      </summary>
      <div className="grid gap-4 border-t border-border p-4 md:grid-cols-2 lg:grid-cols-3">
        <Field label={t("fields.provider")}>
          <ProviderInput value={model.provider} disabled={disabled} onChange={(provider) => onChange({ provider })} />
        </Field>
        <TextInput label={t("fields.name")} value={model.name} disabled={disabled} onChange={(name) => onChange({ name })} />
        <TextInput label={t("fields.id")} value={model.id} disabled={disabled} placeholder={t("placeholders.generatedId")} onChange={(id) => onChange({ id })} />
        <TextInput label={t("fields.maxInputTokens")} value={model.maxInputTokens} disabled={disabled} onChange={(maxInputTokens) => onChange({ maxInputTokens })} />
        <Field label={t("fields.thinking")}>
          <select value={model.thinking} disabled={disabled} onChange={(event) => onChange({ thinking: event.target.value as ThinkingDraft })} className={inputClassName}>
            {thinkingOptions.map((value) => <option key={value || "default"} value={value}>{value ? t(`thinking.${value}`) : t("thinking.default")}</option>)}
          </select>
        </Field>
        <TextInput label={t("fields.thinkingBudgetTokens")} value={model.thinkingBudgetTokens} disabled={openAIFieldsDisabled} onChange={(thinkingBudgetTokens) => onChange({ thinkingBudgetTokens })} />
        <TextInput label={t("fields.baseUrl")} value={model.baseUrl} disabled={openAIFieldsDisabled} onChange={(baseUrl) => onChange({ baseUrl })} />
        <div className="block space-y-1.5">
          <span className="text-xs font-medium text-muted-foreground">{t("fields.vision")}</span>
          <button
            type="button"
            role="switch"
            aria-checked={model.vision}
            disabled={disabled}
            onClick={() => onChange({ vision: !model.vision })}
            className="flex h-9 items-center gap-2 text-sm transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <span aria-hidden="true" className={cn("relative inline-flex h-7 w-12 shrink-0 items-center rounded-full border transition-colors", model.vision ? "border-[#236b86] bg-[#236b86]" : "border-border bg-muted")}>
              <span className={cn("inline-block h-5 w-5 rounded-full bg-background shadow-sm transition-transform", model.vision ? "translate-x-6" : "translate-x-1")} />
            </span>
            <span className="text-muted-foreground">{t("fields.visionHint")}</span>
          </button>
        </div>
        <div className="block space-y-1.5">
          <span className="text-xs font-medium text-muted-foreground">{t("fields.enabled")}</span>
          <button
            type="button"
            role="switch"
            aria-checked={model.enabled}
            disabled={disabled}
            onClick={() => onChange({ enabled: !model.enabled })}
            className="flex h-9 items-center gap-2 text-sm transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <span aria-hidden="true" className={cn("relative inline-flex h-7 w-12 shrink-0 items-center rounded-full border transition-colors", model.enabled ? "border-[#236b86] bg-[#236b86]" : "border-border bg-muted")}>
              <span className={cn("inline-block h-5 w-5 rounded-full bg-background shadow-sm transition-transform", model.enabled ? "translate-x-6" : "translate-x-1")} />
            </span>
            <span className="text-muted-foreground">{t("fields.enabledHint")}</span>
          </button>
        </div>
        <Field label={t("fields.apiKeySource")}>
          <select value={model.apiKeySource} disabled={apiKeyFieldsDisabled} onChange={(event) => onChange(apiKeySourceChangePatch(model, event.target.value as SecretSource))} className={inputClassName}>
            <option value="none">{t("secretSources.none")}</option>
            <option value="raw">{t("secretSources.raw")}</option>
            <option value="env">{t("secretSources.env")}</option>
            <option value="file">{t("secretSources.file")}</option>
          </select>
        </Field>
        {modelApiKeySupported && model.apiKeySource !== "none" ? (
          <Field label={model.apiKeySource === "raw" ? t("fields.apiKey") : t("fields.secretReference")}>
            <div className="relative">
              <KeyRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <input
                type={model.apiKeySource === "raw" ? "password" : "text"}
                value={model.apiKeyValue}
                disabled={disabled}
                placeholder={rawSecretConfigured ? t("placeholders.keepSecret") : undefined}
                autoComplete="new-password"
                onChange={(event) => onChange({ apiKeyValue: event.target.value })}
                className={cn(inputClassName, "pl-9")}
              />
            </div>
          </Field>
        ) : null}
      </div>
    </details>
  );
}
