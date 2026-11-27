"use client";

import { Loader2, RotateCcw } from "lucide-react";
import { useState } from "react";
import { useTranslations } from "next-intl";

import type { KnowledgeSkillConfig, KnowledgeSkillSetting, SkillConfigValue } from "@/lib/api";

type Draft = Record<string, SkillConfigValue | null>;

/** What a draft changes against what config.json has: only those go into the commit. */
export function changedSettings(settings: KnowledgeSkillSetting[], draft: Draft): Draft {
  return Object.fromEntries(
    settings.filter((setting) => (draft[setting.name] ?? null) !== setting.value).map((setting) => [setting.name, draft[setting.name] ?? null]),
  );
}

function SettingInput({
  setting,
  value,
  onChange,
}: {
  setting: KnowledgeSkillSetting;
  value: SkillConfigValue | null;
  onChange: (value: SkillConfigValue | null) => void;
}) {
  const id = `skill-setting-${setting.name}`;
  const cls = "w-full rounded-md border border-border bg-background px-2 py-1 font-mono text-xs";
  switch (setting.type) {
    case "bool":
      return (
        <input
          id={id}
          type="checkbox"
          checked={Boolean(value ?? setting.default)}
          onChange={(event) => onChange(event.target.checked)}
          className="h-4 w-4"
        />
      );
    case "int":
      return (
        <input
          id={id}
          type="number"
          step={1}
          value={value === null ? "" : String(value)}
          placeholder={setting.default === null ? "" : String(setting.default)}
          // Empty means back to the default; anything else must be a whole number, as the Nix option.
          onChange={(event) => onChange(event.target.value === "" ? null : Number(event.target.value))}
          className={cls}
        />
      );
    default:
      return (
        <input
          id={id}
          type="text"
          value={value === null ? "" : String(value)}
          placeholder={setting.default === null ? "" : String(setting.default)}
          onChange={(event) => onChange(event.target.value === "" ? null : event.target.value)}
          className={cls}
        />
      );
  }
}

/** One skill's entry in skills/config.json: on or off, and its settings. Saving commits it. */
export function SkillConfigForm({
  skill,
  saving,
  onSave,
}: {
  skill: KnowledgeSkillConfig;
  saving: boolean;
  onSave: (enable: boolean, settings: Draft) => void;
}) {
  const t = useTranslations("knowledge.skillConfig");
  const settings = skill.settings ?? [];
  const [enabled, setEnabled] = useState(skill.enabled);
  const [draft, setDraft] = useState<Draft>(() => Object.fromEntries(settings.map((setting) => [setting.name, setting.value])));
  const changed = changedSettings(settings, draft);
  const invalid = settings.some((setting) => setting.type === "int" && draft[setting.name] != null && !Number.isInteger(draft[setting.name]));
  const dirty = enabled !== skill.enabled || Object.keys(changed).length > 0;

  return (
    <form
      className="space-y-3 rounded-md bg-inset p-3"
      onSubmit={(event) => {
        event.preventDefault();
        onSave(enabled, changed);
      }}
    >
      <label className="flex items-center gap-2 font-medium">
        <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} className="h-4 w-4" />
        {t("enabled")}
      </label>
      {skill.detail ? <pre className="whitespace-pre-wrap break-words text-xs text-destructive">{skill.detail}</pre> : null}
      {skill.settings === null ? (
        <p className="text-muted-foreground">{t("notKnownYet")}</p>
      ) : settings.length === 0 ? (
        <p className="text-muted-foreground">{t("noSettings")}</p>
      ) : (
        <div className="space-y-2">
          {settings.map((setting) => (
            <div key={setting.name} className="grid gap-1 sm:grid-cols-[12rem_1fr_auto] sm:items-center sm:gap-3">
              <label htmlFor={`skill-setting-${setting.name}`} className="min-w-0">
                <code className="font-mono font-medium">{setting.name}</code>
                {setting.missing && draft[setting.name] == null ? <span className="ml-2 text-warning">{t("required")}</span> : null}
                {setting.description ? <span className="block text-muted-foreground">{setting.description}</span> : null}
              </label>
              <SettingInput
                setting={setting}
                value={draft[setting.name] ?? null}
                onChange={(value) => setDraft((current) => ({ ...current, [setting.name]: value }))}
              />
              <button
                type="button"
                title={t("reset")}
                aria-label={t("reset")}
                disabled={draft[setting.name] == null}
                onClick={() => setDraft((current) => ({ ...current, [setting.name]: null }))}
                className="justify-self-start rounded-md p-1 text-muted-foreground hover:bg-muted disabled:opacity-30"
              >
                <RotateCcw className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}
      <button
        type="submit"
        disabled={!dirty || invalid || saving}
        className="inline-flex items-center gap-1.5 rounded-md bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
        {saving ? t("saving") : t("save")}
      </button>
    </form>
  );
}
