"use client";

import Image from "next/image";
import { Check, CircleHelp, FileText, KeyRound, Loader2, Plus, Save, Trash2, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  getUserSettings,
  updateUserSettings,
  type AvailableModelInfo,
  type CredentialBackendSettingsInfo,
  type CredentialsSettingsInfo,
  type MatrixSettingsInfo,
  type SessionBudgetSettings,
  type UserDefaultModelsSettings,
  type UserSettingsPatchInput,
  type UserSettingsResponseInfo,
} from "@/lib/api";
import { useAppShell } from "@/components/app-shell-context";
import { ChatGptSubscriptionPanel } from "@/components/chatgpt-subscription-panel";
import { ModelPicker, withSelectedModelOption } from "@/components/model-picker";
import { SwitchRow } from "@/components/switch-row";
import { resolveBundledEmojiAsset, splitEmojiText } from "@/lib/emoji";
import { cn } from "@/lib/utils";

interface UserSettingsDraft {
  agentName: string;
  agentIcon: string;
  defaultModels: UserDefaultModelsSettings;
  budget: Record<keyof Required<SessionBudgetSettings>, string>;
  matrix: MatrixSettingsInfo;
  matrixPassword: string;
  credentials: CredentialBackendDraft[];
  git: {
    remote: string;
    branch: string;
    author: string;
    token_set: boolean;
  };
  gitToken: string;
}

type CredentialBackendDraftType = "file" | "bitwarden";

interface CredentialBackendDraft {
  id: string;
  name: string;
  type: CredentialBackendDraftType;
  path: string;
  url: string;
  expose: string;
  hide: string;
  basicAuthEnabled: boolean;
  basicAuthUsername: string;
  basicAuthPassword: string;
  basicAuthPasswordSet: boolean;
}

type Translate = (key: string, values?: Record<string, string | number>) => string;

const DEFAULT_AGENT_ICON = "/icon.svg";

const inputClassName = cn(
  "w-full rounded-xl border border-border bg-background px-3 py-2.5 text-sm",
  "outline-none transition-colors placeholder:text-muted-foreground/50",
  "focus:border-ring focus:ring-2 focus:ring-ring/30",
);

let credentialDraftId = 0;

function nextCredentialDraftId(): string {
  credentialDraftId += 1;
  return `credential-backend-${credentialDraftId}`;
}

function linesToArray(value: string): string[] {
  return value.split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean);
}

function arrayToLines(values: string[]): string {
  return values.join("\n");
}

function credentialDraftFromBackend(name: string, backend: CredentialBackendSettingsInfo): CredentialBackendDraft {
  if (backend.type === "file") {
    return {
      id: nextCredentialDraftId(),
      name,
      type: "file",
      path: backend.path,
      url: "http://127.0.0.1:8087",
      expose: arrayToLines(backend.expose),
      hide: arrayToLines(backend.hide),
      basicAuthEnabled: false,
      basicAuthUsername: "",
      basicAuthPassword: "",
      basicAuthPasswordSet: false,
    };
  }

  return {
    id: nextCredentialDraftId(),
    name,
    type: "bitwarden",
    path: "",
    url: backend.url,
    expose: arrayToLines(backend.expose),
    hide: arrayToLines(backend.hide),
    basicAuthEnabled: backend.basic_auth !== null && backend.basic_auth !== undefined,
    basicAuthUsername: backend.basic_auth?.username ?? "",
    basicAuthPassword: "",
    basicAuthPasswordSet: backend.basic_auth?.password_set ?? false,
  };
}

function credentialDraftsFromSettings(credentials: CredentialsSettingsInfo): CredentialBackendDraft[] {
  return Object.entries(credentials.backends)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([name, backend]) => credentialDraftFromBackend(name, backend));
}

function comparableCredentialsFromDraft(backendsDraft: CredentialBackendDraft[]): unknown[] {
  return backendsDraft
    .map((backend) => {
      const expose = linesToArray(backend.expose);
      const hide = linesToArray(backend.hide);
      if (backend.type === "file") {
        return {
          name: backend.name.trim(),
          type: "file",
          path: backend.path.trim(),
          expose,
          hide,
        };
      }

      return {
        name: backend.name.trim(),
        type: "bitwarden",
        url: backend.url.trim() || "http://127.0.0.1:8087",
        basic_auth: backend.basicAuthEnabled
          ? {
              username: backend.basicAuthUsername.trim(),
              password_set: backend.basicAuthPasswordSet,
              password_changed: backend.basicAuthPassword.length > 0,
            }
          : null,
        expose,
        hide,
      };
    })
    .sort((left, right) => {
      if (typeof left !== "object" || left === null || !("name" in left)) return 0;
      if (typeof right !== "object" || right === null || !("name" in right)) return 0;
      return String(left.name).localeCompare(String(right.name));
    });
}

function comparableCredentialsFromSettings(credentials: CredentialsSettingsInfo): unknown[] {
  return Object.entries(credentials.backends)
    .map(([name, backend]) => {
      if (backend.type === "file") {
        return {
          name,
          type: "file",
          path: backend.path,
          expose: backend.expose,
          hide: backend.hide,
        };
      }

      return {
        name,
        type: "bitwarden",
        url: backend.url,
        basic_auth: backend.basic_auth
          ? {
              username: backend.basic_auth.username,
              password_set: backend.basic_auth.password_set,
              password_changed: false,
            }
          : null,
        expose: backend.expose,
        hide: backend.hide,
      };
    })
    .sort((left, right) => left.name.localeCompare(right.name));
}

function uniqueCredentialBackendName(type: CredentialBackendDraftType, backends: CredentialBackendDraft[]): string {
  const base = type === "file" ? "file" : "bitwarden";
  const names = new Set(backends.map((backend) => backend.name.trim()).filter(Boolean));
  if (!names.has(base)) return base;
  for (let index = 2; index < 1000; index += 1) {
    const candidate = `${base}-${index}`;
    if (!names.has(candidate)) return candidate;
  }
  return `${base}-${Date.now()}`;
}

function newCredentialBackendDraft(
  type: CredentialBackendDraftType,
  backends: CredentialBackendDraft[],
): CredentialBackendDraft {
  return {
    id: nextCredentialDraftId(),
    name: uniqueCredentialBackendName(type, backends),
    type,
    path: "",
    url: "http://127.0.0.1:8087",
    expose: "",
    hide: "",
    basicAuthEnabled: false,
    basicAuthUsername: "",
    basicAuthPassword: "",
    basicAuthPasswordSet: false,
  };
}

function credentialsFromDraft(
  backendsDraft: CredentialBackendDraft[],
  fileBackendAllowed: boolean,
  t: Translate,
): { backends: Record<string, unknown> } {
  const names = new Set<string>();
  const backends: Record<string, unknown> = {};

  for (const backend of backendsDraft) {
    const name = backend.name.trim();
    if (!name) throw new Error(t("errors.credentialNameRequired"));
    if (name.includes("/")) throw new Error(t("errors.credentialNameNoSlash", { name }));
    if (names.has(name)) throw new Error(t("errors.credentialNameDuplicate", { name }));
    names.add(name);

    const expose = linesToArray(backend.expose);
    const hide = linesToArray(backend.hide);
    if (backend.type === "file") {
      if (!fileBackendAllowed) throw new Error(t("errors.fileBackendDisabled"));
      backends[name] = {
        type: "file",
        path: backend.path.trim(),
        expose,
        hide,
      };
      continue;
    }

    let basicAuth: Record<string, string> | undefined;
    if (backend.basicAuthEnabled) {
      const username = backend.basicAuthUsername.trim();
      if (!username) throw new Error(t("errors.basicAuthUsernameRequired", { name }));
      if (!backend.basicAuthPassword && !backend.basicAuthPasswordSet) {
        throw new Error(t("errors.basicAuthPasswordRequired", { name }));
      }
      basicAuth = {
        username,
        ...(backend.basicAuthPassword ? { password: backend.basicAuthPassword } : {}),
      };
    }

    backends[name] = {
      type: "bitwarden",
      url: backend.url.trim() || "http://127.0.0.1:8087",
      ...(basicAuth ? { basic_auth: basicAuth } : {}),
      expose,
      hide,
    };
  }

  return { backends };
}

function budgetValue(value: number | string | null | undefined): string {
  if (value === null || value === undefined) return "";
  return String(value);
}

function budgetCostValue(value: number | string | null | undefined): string {
  const rawValue = budgetValue(value).trim();
  if (!rawValue) return "";
  const normalized = rawValue.replaceAll(",", "").replaceAll("_", "");
  const parsed = Number(normalized);
  if (parsed === 0) return "";
  return Number.isFinite(parsed) ? parsed.toFixed(2) : rawValue;
}

function draftFromSettings(response: UserSettingsResponseInfo): UserSettingsDraft {
  const budget = response.settings.default_budget;
  return {
    agentName: response.settings.agent_name,
    agentIcon: response.settings.agent_icon,
    defaultModels: response.settings.default_models,
    budget: {
      input_tokens: budgetValue(budget.input_tokens),
      output_tokens: budgetValue(budget.output_tokens),
      cost_usd: budgetCostValue(budget.cost_usd),
      tool_calls: budgetValue(budget.tool_calls),
    },
    matrix: response.settings.matrix,
    matrixPassword: "",
    credentials: credentialDraftsFromSettings(response.settings.credentials),
    git: response.settings.git,
    gitToken: "",
  };
}

function parseOptionalBudgetInteger(value: string, label: string, t: Translate): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const normalized = trimmed.replaceAll(",", "").replaceAll("_", "");
  const parsed = Number(normalized);
  if (!/^\d+$/.test(normalized) || !Number.isSafeInteger(parsed)) {
    throw new Error(t("errors.budgetWholeNumber", { field: label }));
  }
  return parsed;
}

function parseOptionalBudgetDecimal(value: string, label: string, t: Translate): string | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const normalized = trimmed.replaceAll(",", "").replaceAll("_", "");
  if (!/^\d+(\.\d+)?$/.test(normalized) || !Number.isFinite(Number(normalized))) {
    throw new Error(t("errors.budgetNumber", { field: label }));
  }
  return normalized;
}

function parseOptionalBudgetCost(value: string, label: string, t: Translate): string | null {
  const parsed = parseOptionalBudgetDecimal(value, label, t);
  if (parsed === null) return null;
  const cost = Number(parsed);
  return cost === 0 ? null : cost.toFixed(2);
}

function comparableBudgetInteger(value: string | number | null | undefined): number | string | null {
  const normalized = budgetValue(value).trim().replaceAll(",", "").replaceAll("_", "");
  if (!normalized) return null;
  if (!/^\d+$/.test(normalized)) return `invalid:${normalized}`;
  const parsed = Number(normalized);
  return parsed === 0 ? null : parsed;
}

function comparableBudgetCost(value: string | number | null | undefined): string | null {
  const normalized = budgetCostValue(value);
  return normalized || null;
}

function comparableBudget(budget: Record<keyof Required<SessionBudgetSettings>, string> | SessionBudgetSettings): unknown {
  return {
    input_tokens: comparableBudgetInteger(budget.input_tokens),
    output_tokens: comparableBudgetInteger(budget.output_tokens),
    cost_usd: comparableBudgetCost(budget.cost_usd),
    tool_calls: comparableBudgetInteger(budget.tool_calls),
  };
}

function comparableDefaultModels(models: UserDefaultModelsSettings): unknown {
  return {
    agent: models.agent?.trim() || null,
    sentinel: models.sentinel?.trim() || null,
    title: models.title?.trim() || null,
  };
}

function comparableDraft(draft: UserSettingsDraft): unknown {
  return {
    agent_name: draft.agentName.trim(),
    agent_icon: draft.agentIcon.trim(),
    default_models: comparableDefaultModels(draft.defaultModels),
    default_budget: comparableBudget(draft.budget),
    matrix: {
      ...draft.matrix,
      password_changed: draft.matrixPassword.length > 0,
    },
    credentials: comparableCredentialsFromDraft(draft.credentials),
    git: {
      remote: draft.git.remote,
      branch: draft.git.branch,
      author: draft.git.author,
      token_set: draft.git.token_set,
      token_changed: draft.gitToken.length > 0,
    },
  };
}

function comparableSettings(settings: UserSettingsResponseInfo): unknown {
  return {
    agent_name: settings.settings.agent_name.trim(),
    agent_icon: settings.settings.agent_icon.trim(),
    default_models: comparableDefaultModels(settings.settings.default_models),
    default_budget: comparableBudget(settings.settings.default_budget),
    matrix: {
      ...settings.settings.matrix,
      password_changed: false,
    },
    credentials: comparableCredentialsFromSettings(settings.settings.credentials),
    git: {
      ...settings.settings.git,
      token_changed: false,
    },
  };
}

function userSettingsChanged(draft: UserSettingsDraft | null, settings: UserSettingsResponseInfo | null): boolean {
  if (!draft || !settings) return false;
  return JSON.stringify(comparableDraft(draft)) !== JSON.stringify(comparableSettings(settings));
}

function credentialsChanged(draft: UserSettingsDraft, settings: UserSettingsResponseInfo): boolean {
  return JSON.stringify(comparableCredentialsFromDraft(draft.credentials)) !== JSON.stringify(comparableCredentialsFromSettings(settings.settings.credentials));
}

function budgetFromDraft(draft: UserSettingsDraft, t: Translate): SessionBudgetSettings {
  return {
    input_tokens: parseOptionalBudgetInteger(draft.budget.input_tokens, t("fields.inputTokens"), t),
    output_tokens: parseOptionalBudgetInteger(draft.budget.output_tokens, t("fields.outputTokens"), t),
    cost_usd: parseOptionalBudgetCost(draft.budget.cost_usd, t("fields.costUsd"), t),
    tool_calls: parseOptionalBudgetInteger(draft.budget.tool_calls, t("fields.toolCalls"), t),
  };
}

export function buildUserSettingsPatch(
  draft: UserSettingsDraft,
  settings: UserSettingsResponseInfo,
  t: Translate,
): UserSettingsPatchInput {
  const includeCredentials = credentialsChanged(draft, settings);
  let credentialsPayload: unknown;
  if (includeCredentials) {
    credentialsPayload = credentialsFromDraft(
      draft.credentials,
      settings.capabilities.file_credential_backend,
      t,
    );
  }

  if (draft.matrix.enabled && !draft.matrix.password_set && !draft.matrix.token_set && !draft.matrixPassword.trim()) {
    throw new Error(t("errors.matrixPasswordRequired"));
  }

  const body: UserSettingsPatchInput = {
    agent_name: draft.agentName.trim(),
    agent_icon: draft.agentIcon.trim(),
    // Spread so stored models this view does not edit pass through unchanged.
    default_models: {
      ...draft.defaultModels,
      agent: draft.defaultModels.agent?.trim() || null,
      sentinel: draft.defaultModels.sentinel?.trim() || null,
      title: draft.defaultModels.title?.trim() || null,
    },
    default_budget: budgetFromDraft(draft, t),
    matrix: {
      enabled: draft.matrix.enabled,
      homeserver: draft.matrix.homeserver,
      user_id: draft.matrix.user_id,
      device_name: draft.matrix.device_name,
      allowed_rooms: draft.matrix.allowed_rooms,
      allowed_users: draft.matrix.allowed_users,
      ...(draft.matrixPassword ? { password: draft.matrixPassword, clear_token: true } : {}),
    },
    git: {
      remote: draft.git.remote,
      branch: draft.git.branch,
      author: draft.git.author,
      ...(draft.gitToken ? { token: draft.gitToken } : {}),
    },
  };
  if (includeCredentials) {
    body.credentials = credentialsPayload;
  }
  return body;
}

export function UserSettingsView({ server, token }: { server: string; token: string }) {
  const t = useTranslations("accountSettings");
  const { onRefreshCurrentUser } = useAppShell();
  const [settings, setSettings] = useState<UserSettingsResponseInfo | null>(null);
  const [draft, setDraft] = useState<UserSettingsDraft | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadSettings = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await getUserSettings(server, token);
      setSettings(response);
      setDraft(draftFromSettings(response));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : t("errors.load"));
    } finally {
      setLoading(false);
    }
  }, [server, t, token]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadSettings();
    }, 0);
    return () => {
      window.clearTimeout(timer);
    };
  }, [loadSettings]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => {
      setNotice(null);
    }, 30_000);
    return () => {
      window.clearTimeout(timer);
    };
  }, [notice]);

  const availableModels: AvailableModelInfo[] = useMemo(
    () => settings?.available_models ?? [],
    [settings?.available_models],
  );
  const agentOptions = useMemo(
    () => withSelectedModelOption(availableModels, draft?.defaultModels.agent),
    [availableModels, draft?.defaultModels.agent],
  );
  const sentinelOptions = useMemo(
    () => withSelectedModelOption(availableModels, draft?.defaultModels.sentinel),
    [availableModels, draft?.defaultModels.sentinel],
  );
  const titleOptions = useMemo(
    () => withSelectedModelOption(availableModels, draft?.defaultModels.title),
    [availableModels, draft?.defaultModels.title],
  );
  const settingsChanged = useMemo(
    () => userSettingsChanged(draft, settings),
    [draft, settings],
  );

  function updateDraft(patch: Partial<UserSettingsDraft>): void {
    setNotice(null);
    setDraft((current) => current ? { ...current, ...patch } : current);
  }

  function updateMatrix(patch: Partial<MatrixSettingsInfo>): void {
    setNotice(null);
    setDraft((current) => current ? { ...current, matrix: { ...current.matrix, ...patch } } : current);
  }

  function updateCredentialBackend(id: string, patch: Partial<CredentialBackendDraft>): void {
    setNotice(null);
    setDraft((current) => current ? {
      ...current,
      credentials: current.credentials.map((backend) => backend.id === id ? { ...backend, ...patch } : backend),
    } : current);
  }

  function addCredentialBackend(type: CredentialBackendDraftType): void {
    setNotice(null);
    setDraft((current) => current ? {
      ...current,
      credentials: [...current.credentials, newCredentialBackendDraft(type, current.credentials)],
    } : current);
  }

  function removeCredentialBackend(id: string): void {
    setNotice(null);
    setDraft((current) => current ? {
      ...current,
      credentials: current.credentials.filter((backend) => backend.id !== id),
    } : current);
  }

  async function handleSave(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!draft || !settings || !settingsChanged) return;

    let body: UserSettingsPatchInput;
    try {
      body = buildUserSettingsPatch(draft, settings, t);
    } catch (settingsError) {
      setError(settingsError instanceof Error ? settingsError.message : t("errors.save"));
      setNotice(null);
      return;
    }

    setSaving(true);
    setError(null);
    try {
      const response = await updateUserSettings(server, token, body);
      setSettings(response);
      setDraft(draftFromSettings(response));
      onRefreshCurrentUser();
      setNotice(t("notices.saved"));
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : t("errors.save"));
      setNotice(null);
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        {t("status.loading")}
      </div>
    );
  }

  if (!draft || !settings) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center px-6 text-sm text-destructive">
        {error ?? t("status.unavailable")}
      </div>
    );
  }

  return (
    <form onSubmit={(event) => void handleSave(event)} className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-6">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className={cn("min-h-5 text-sm", error ? "text-destructive" : "text-muted-foreground")}>
            {error ? error : notice ? <span className="inline-flex items-center gap-2"><Check className="h-4 w-4" />{notice}</span> : null}
          </div>
          <button
            type="submit"
            disabled={saving || !settingsChanged}
            className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-background transition-colors hover:bg-foreground/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            {saving ? t("actions.saving") : t("actions.save")}
          </button>
        </div>

        <Section title={t("sections.appearance")}>
          <div className="grid gap-4 md:grid-cols-2">
            <TextInput
              label={t("fields.agentName")}
              value={draft.agentName}
              hint={t("hints.agentName")}
              onChange={(agentName) => updateDraft({ agentName })}
            />
            <EmojiInput
              label={t("fields.agentIcon")}
              value={draft.agentIcon}
              hint={t("hints.agentIcon")}
              onChange={(agentIcon) => updateDraft({ agentIcon })}
            />
          </div>
        </Section>

        <Section title={t("sections.defaultModels")}>
          <div className="grid gap-4 lg:grid-cols-3">
            <Field label={t("fields.agent")}>
              <ModelPicker
                value={draft.defaultModels.agent}
                entries={agentOptions}
                onChange={(agent) => updateDraft({ defaultModels: { ...draft.defaultModels, agent } })}
                disabled={saving}
                defaultLabel={t("defaults.serverDefault")}
                defaultDescription={t("defaults.currentModel", { model: settings.server_defaults.models.agent || t("defaults.serverDefault") })}
              />
            </Field>
            <Field label={t("fields.sentinel")}>
              <ModelPicker
                value={draft.defaultModels.sentinel}
                entries={sentinelOptions}
                onChange={(sentinel) => updateDraft({ defaultModels: { ...draft.defaultModels, sentinel } })}
                disabled={saving}
                defaultLabel={t("defaults.serverDefault")}
                defaultDescription={t("defaults.currentModel", { model: settings.server_defaults.models.sentinel || t("defaults.serverDefault") })}
              />
            </Field>
            <Field label={t("fields.title")}>
              <ModelPicker
                value={draft.defaultModels.title}
                entries={titleOptions}
                onChange={(title) => updateDraft({ defaultModels: { ...draft.defaultModels, title } })}
                disabled={saving}
                defaultLabel={t("defaults.serverDefault")}
                defaultDescription={t("defaults.currentModel", { model: settings.server_defaults.models.title || t("defaults.serverDefault") })}
              />
            </Field>
          </div>
        </Section>

        <Section title={t("sections.chatgpt")}>
          <ChatGptSubscriptionPanel server={server} token={token} />
        </Section>

        <Section title={t("sections.defaultBudgets")}>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <BudgetInput label={t("fields.inputTokens")} placeholder={t("defaults.serverDefault")} value={draft.budget.input_tokens} onChange={(value) => updateDraft({ budget: { ...draft.budget, input_tokens: value } })} />
            <BudgetInput label={t("fields.outputTokens")} placeholder={t("defaults.serverDefault")} value={draft.budget.output_tokens} onChange={(value) => updateDraft({ budget: { ...draft.budget, output_tokens: value } })} />
            <BudgetInput label={t("fields.costUsd")} placeholder={t("defaults.serverDefault")} value={draft.budget.cost_usd} onBlur={() => updateDraft({ budget: { ...draft.budget, cost_usd: budgetCostValue(draft.budget.cost_usd) } })} onChange={(value) => updateDraft({ budget: { ...draft.budget, cost_usd: value } })} />
            <BudgetInput label={t("fields.toolCalls")} placeholder={t("defaults.serverDefault")} value={draft.budget.tool_calls} onChange={(value) => updateDraft({ budget: { ...draft.budget, tool_calls: value } })} />
          </div>
        </Section>

        <Section title={t("sections.gitRemote")}>
          <div className="grid gap-4 md:grid-cols-2">
            <TextInput
              label={t("fields.remote")}
              value={draft.git.remote}
              name="git-remote-url"
              disablePasswordManager
              onChange={(remote) => updateDraft({ git: { ...draft.git, remote } })}
            />
            <TextInput label={t("fields.branch")} value={draft.git.branch} onChange={(branch) => updateDraft({ git: { ...draft.git, branch } })} />
            <TextInput label={t("fields.author")} value={draft.git.author} onChange={(author) => updateDraft({ git: { ...draft.git, author } })} />
            <WriteOnlyPasswordInput
              label={t("fields.token")}
              configured={draft.git.token_set}
              configuredLabel={t("status.configured")}
              notSetLabel={t("status.notSet")}
              value={draft.gitToken}
              name="git-remote-token"
              disablePasswordManager
              onValueChange={(gitToken) => updateDraft({ gitToken })}
            />
          </div>
        </Section>

        <Section title={t("sections.credentials")}>
          <div className="space-y-4">
            <div className="flex flex-wrap justify-end gap-2">
              <SecondaryButton onClick={() => addCredentialBackend("bitwarden")} disabled={saving}>
                <Plus className="h-4 w-4" />
                {t("actions.addBitwarden")}
              </SecondaryButton>
              {settings.capabilities.file_credential_backend ? (
                <SecondaryButton onClick={() => addCredentialBackend("file")} disabled={saving}>
                  <Plus className="h-4 w-4" />
                  {t("actions.addFile")}
                </SecondaryButton>
              ) : null}
            </div>
            {draft.credentials.length ? (
              <div className="space-y-3">
                {draft.credentials.map((backend) => (
                  <CredentialBackendEditor
                    key={backend.id}
                    backend={backend}
                    onChange={(patch) => updateCredentialBackend(backend.id, patch)}
                    onRemove={() => removeCredentialBackend(backend.id)}
                    t={t}
                    disabled={saving}
                  />
                ))}
              </div>
            ) : (
              <div className="rounded-lg border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground">
                {t("empty.credentials")}
              </div>
            )}
          </div>
        </Section>

        <Section title={t("sections.matrix")}>
          <div className="space-y-4">
            <SwitchRow checked={draft.matrix.enabled} label={t("fields.enabled")} onCheckedChange={(enabled) => updateMatrix({ enabled })} />
            {draft.matrix.enabled ? (
              <div className="grid gap-4 md:grid-cols-2">
                <TextInput label={t("fields.homeserver")} value={draft.matrix.homeserver} onChange={(homeserver) => updateMatrix({ homeserver })} />
                <TextInput label={t("fields.userId")} value={draft.matrix.user_id} onChange={(user_id) => updateMatrix({ user_id })} />
                <TextInput label={t("fields.deviceName")} value={draft.matrix.device_name} onChange={(device_name) => updateMatrix({ device_name })} />
                <WriteOnlyPasswordInput
                  label={t("fields.password")}
                  configured={draft.matrix.password_set}
                  configuredLabel={t("status.configured")}
                  notSetLabel={t("status.notSet")}
                  value={draft.matrixPassword}
                  name="matrix-credential-secret"
                  disablePasswordManager
                  onValueChange={(matrixPassword) => updateDraft({ matrixPassword })}
                />
                <FreeInputMultiSelect label={t("fields.allowedRooms")} values={draft.matrix.allowed_rooms} placeholder={t("placeholders.addRoom")} removeTitle={t("actions.remove")} removeAriaLabel={(value) => t("actions.removeValue", { value })} onChange={(allowed_rooms) => updateMatrix({ allowed_rooms })} />
                <FreeInputMultiSelect label={t("fields.allowedUsers")} values={draft.matrix.allowed_users} placeholder={t("placeholders.addUser")} removeTitle={t("actions.remove")} removeAriaLabel={(value) => t("actions.removeValue", { value })} onChange={(allowed_users) => updateMatrix({ allowed_users })} />
              </div>
            ) : null}
          </div>
        </Section>
      </div>
    </form>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-border bg-background/88 p-4 shadow-sm sm:p-5">
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-[0.14em] text-muted-foreground">{title}</h2>
      {children}
    </section>
  );
}

function Field({ label, hint, help, children }: { label: string; hint?: string; help?: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        {label}
        {help ? (
          <span
            title={help}
            aria-label={help}
            className="inline-flex h-4 w-4 items-center justify-center rounded text-muted-foreground transition-colors hover:text-foreground"
          >
            <CircleHelp className="h-3.5 w-3.5" />
          </span>
        ) : null}
      </span>
      {children}
      {hint ? <span className="block text-xs text-muted-foreground">{hint}</span> : null}
    </label>
  );
}

function EmojiInput({
  label,
  hint,
  value,
  onChange,
}: {
  label: string;
  hint?: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const preview = resolveBundledEmojiAsset(value);
  return (
    <Field label={label} hint={hint}>
      <div className="flex items-center gap-2">
        <input
          value={value}
          onChange={(event) => onChange(firstBundledEmoji(event.target.value))}
          className={cn(inputClassName, "min-w-0 flex-1")}
        />
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-border">
          <Image
            src={preview ?? DEFAULT_AGENT_ICON}
            alt=""
            width={22}
            height={22}
            aria-hidden="true"
            className={preview ? undefined : "opacity-30"}
          />
        </span>
      </div>
    </Field>
  );
}

// Only emoji bundled as SVG assets can be rendered as an icon, so anything else is
// dropped on input rather than stored as a value that silently shows the default.
function firstBundledEmoji(value: string): string {
  return splitEmojiText(value).find((segment) => segment.kind === "emoji")?.value ?? "";
}

function TextInput({
  label,
  hint,
  help,
  value,
  name,
  disablePasswordManager = false,
  onChange,
}: {
  label: string;
  hint?: string;
  help?: string;
  value: string;
  name?: string;
  disablePasswordManager?: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <Field label={label} hint={hint} help={help}>
      <input
        name={name}
        autoComplete={disablePasswordManager ? "off" : undefined}
        data-1p-ignore={disablePasswordManager ? "true" : undefined}
        data-bwignore={disablePasswordManager ? "true" : undefined}
        data-lpignore={disablePasswordManager ? "true" : undefined}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={inputClassName}
      />
    </Field>
  );
}

function FreeInputMultiSelect({
  label,
  values,
  placeholder,
  help,
  removeTitle,
  removeAriaLabel,
  onChange,
}: {
  label: string;
  values: string[];
  placeholder: string;
  help?: string;
  removeTitle: string;
  removeAriaLabel: (value: string) => string;
  onChange: (values: string[]) => void;
}) {
  const [inputValue, setInputValue] = useState("");

  function addFromText(text: string): void {
    const additions = linesToArray(text);
    if (!additions.length) return;
    const nextValues = [...values];
    for (const addition of additions) {
      if (!nextValues.includes(addition)) nextValues.push(addition);
    }
    onChange(nextValues);
  }

  function removeValue(value: string): void {
    onChange(values.filter((item) => item !== value));
  }

  function commitInput(): void {
    addFromText(inputValue);
    setInputValue("");
  }

  return (
    <div className="space-y-1.5">
      <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        {label}
        {help ? (
          <span
            title={help}
            aria-label={help}
            className="inline-flex h-4 w-4 items-center justify-center rounded text-muted-foreground transition-colors hover:text-foreground"
          >
            <CircleHelp className="h-3.5 w-3.5" />
          </span>
        ) : null}
      </span>
      <div className={cn(inputClassName, "flex min-h-11 flex-wrap items-center gap-1.5 py-1.5")}>
        {values.map((value) => (
          <span
            key={value}
            className="inline-flex min-h-7 max-w-full items-center gap-1 rounded-md border border-border bg-muted px-2 text-xs text-foreground"
          >
            <span className="truncate">{value}</span>
            <button
              type="button"
              onClick={() => removeValue(value)}
              className="inline-flex h-5 w-5 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-background hover:text-foreground"
              aria-label={removeAriaLabel(value)}
              title={removeTitle}
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </span>
        ))}
        <input
          value={inputValue}
          onChange={(event) => {
            const value = event.target.value;
            if (/[,\n\r]/.test(value)) {
              addFromText(value);
              setInputValue("");
              return;
            }
            setInputValue(value);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === "Tab" || event.key === ",") {
              if (inputValue.trim()) {
                event.preventDefault();
                commitInput();
              }
            }
            if (event.key === "Backspace" && !inputValue && values.length) {
              event.preventDefault();
              onChange(values.slice(0, -1));
            }
          }}
          onBlur={commitInput}
          placeholder={values.length ? "" : placeholder}
          className="min-h-8 min-w-32 flex-1 bg-transparent px-1 text-sm outline-none placeholder:text-muted-foreground/50"
        />
      </div>
    </div>
  );
}

function BudgetInput({ label, placeholder, value, onBlur, onChange }: { label: string; placeholder: string; value: string; onBlur?: () => void; onChange: (value: string) => void }) {
  return (
    <Field label={label}>
      <input inputMode="decimal" value={value} onBlur={onBlur} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className={inputClassName} />
    </Field>
  );
}

function SecondaryButton({
  children,
  onClick,
  disabled = false,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg border border-border bg-background px-3 py-2 text-sm font-medium transition-colors hover:bg-muted/60 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {children}
    </button>
  );
}

function CredentialBackendEditor({
  backend,
  onChange,
  onRemove,
  t,
  disabled,
}: {
  backend: CredentialBackendDraft;
  onChange: (patch: Partial<CredentialBackendDraft>) => void;
  onRemove: () => void;
  t: Translate;
  disabled: boolean;
}) {
  const typeLabel = backend.type === "file" ? t("credentials.types.file.label") : t("credentials.types.bitwarden.label");
  const typeDescription = backend.type === "file" ? t("credentials.types.file.description") : t("credentials.types.bitwarden.description");
  const TypeIcon = backend.type === "file" ? FileText : KeyRound;
  return (
    <div className="rounded-lg border border-border bg-muted/20 p-4">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-border bg-background text-muted-foreground">
            <TypeIcon className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <div className="text-sm font-medium text-foreground">{typeLabel}</div>
            <div className="text-xs text-muted-foreground">{typeDescription}</div>
          </div>
        </div>
        <button
          type="button"
          onClick={onRemove}
          disabled={disabled}
          className="inline-flex min-h-10 w-10 items-center justify-center rounded-lg border border-border text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive disabled:cursor-not-allowed disabled:opacity-50"
          aria-label={t("actions.removeBackendAria", { name: backend.name || t("credentials.backendFallback") })}
          title={t("actions.removeBackend")}
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>

      {backend.type === "file" ? (
        <div className="grid gap-4 md:grid-cols-2">
          <TextInput label={t("fields.name")} value={backend.name} onChange={(name) => onChange({ name })} />
          <TextInput
            label={t("fields.path")}
            help={t("tooltips.filePath")}
            value={backend.path}
            onChange={(path) => onChange({ path })}
          />
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <TextInput label={t("fields.name")} value={backend.name} onChange={(name) => onChange({ name })} />
            <TextInput label={t("fields.url")} value={backend.url} onChange={(url) => onChange({ url })} />
          </div>
          <SwitchRow
            checked={backend.basicAuthEnabled}
            label={t("fields.basicAuth")}
            onCheckedChange={(basicAuthEnabled) => onChange({ basicAuthEnabled })}
          />
          {backend.basicAuthEnabled ? (
            <div className="grid gap-4 md:grid-cols-2">
              <TextInput
                label={t("fields.basicAuthUsername")}
                value={backend.basicAuthUsername}
                onChange={(basicAuthUsername) => onChange({ basicAuthUsername })}
              />
              <WriteOnlyPasswordInput
                label={t("fields.basicAuthPassword")}
                configured={backend.basicAuthPasswordSet}
                configuredLabel={t("status.configured")}
                notSetLabel={t("status.notSet")}
                value={backend.basicAuthPassword}
                onValueChange={(basicAuthPassword) => onChange({ basicAuthPassword })}
              />
            </div>
          ) : null}
        </div>
      )}

      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <FreeInputMultiSelect
          label={t("fields.expose")}
          values={linesToArray(backend.expose)}
          placeholder={t("placeholders.addIdentifier")}
          help={t("tooltips.expose")}
          removeTitle={t("actions.remove")}
          removeAriaLabel={(value) => t("actions.removeValue", { value })}
          onChange={(expose) => onChange({ expose: arrayToLines(expose) })}
        />
        <FreeInputMultiSelect
          label={t("fields.hide")}
          values={linesToArray(backend.hide)}
          placeholder={t("placeholders.addIdentifier")}
          help={t("tooltips.hide")}
          removeTitle={t("actions.remove")}
          removeAriaLabel={(value) => t("actions.removeValue", { value })}
          onChange={(hide) => onChange({ hide: arrayToLines(hide) })}
        />
      </div>
    </div>
  );
}

function WriteOnlyPasswordInput({
  label,
  configured,
  configuredLabel,
  notSetLabel,
  value,
  name,
  disablePasswordManager = false,
  onValueChange,
}: {
  label: string;
  configured: boolean;
  configuredLabel: string;
  notSetLabel: string;
  value: string;
  name?: string;
  disablePasswordManager?: boolean;
  onValueChange: (value: string) => void;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-3">
        <span className="block text-xs font-medium text-muted-foreground">{label}</span>
        <span className="text-xs text-muted-foreground">{configured ? configuredLabel : notSetLabel}</span>
      </div>
      <input
        type="password"
        name={name}
        autoComplete={disablePasswordManager ? "new-password" : undefined}
        data-1p-ignore={disablePasswordManager ? "true" : undefined}
        data-bwignore={disablePasswordManager ? "true" : undefined}
        data-lpignore={disablePasswordManager ? "true" : undefined}
        value={value}
        onChange={(event) => onValueChange(event.target.value)}
        className={inputClassName}
      />
    </div>
  );
}
