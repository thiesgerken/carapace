"use client";

import { ArrowUpCircle, CircleAlert, CircleCheck, CircleDashed, GitBranch, Loader2, RefreshCw, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { Fragment, useEffect, useState, type ReactNode } from "react";
import { useLocale, useTranslations } from "next-intl";

import {
  applySkillUpdate,
  checkSkillUpdates,
  fetchSkillsConfig,
  fetchSkillSources,
  saveSkillConfig,
  type KnowledgeSkillsConfig,
  type KnowledgeSkillSource,
  type KnowledgeSkillSources,
  type SkillConfigValue,
} from "@/lib/api";
import { formatAbsoluteTime } from "@/lib/format-time";
import { knowledgeBrowseHref } from "@/lib/knowledge-links";

import { SkillConfigForm } from "./skill-config-form";

const POLL_MS = 2000;

function formatDate(iso: string | null, locale: string): string {
  return iso ? new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(Date.parse(iso)) : "";
}

/** A tarball or file input has no rev, only the time it was locked. */
function Rev({ rev, at, locale }: { rev: string | null; at: string | null; locale: string }) {
  return (
    <span className="whitespace-nowrap">
      {rev ? <code className="mr-1.5 font-mono" title={rev}>{rev.slice(0, 7)}</code> : null}
      {at ? <span>{formatDate(at, locale)}</span> : null}
    </span>
  );
}

function UpdateCell({
  skill,
  locale,
  applying,
  onApply,
}: {
  skill: KnowledgeSkillSource;
  locale: string;
  applying: boolean;
  onApply: () => void;
}) {
  const t = useTranslations("knowledge.skillSources.update");
  const update = skill.update;
  const states: Record<string, { icon: ReactNode; cls: string; label: string }> = {
    unchecked: { icon: <CircleDashed className="h-3.5 w-3.5" />, cls: "text-muted-foreground", label: t("unchecked") },
    current: { icon: <CircleCheck className="h-3.5 w-3.5" />, cls: "text-success", label: t("current") },
    available: { icon: <ArrowUpCircle className="h-3.5 w-3.5" />, cls: "text-primary", label: t("available") },
    outdated: { icon: <CircleAlert className="h-3.5 w-3.5" />, cls: "text-warning", label: t("outdated") },
    failed: { icon: <CircleAlert className="h-3.5 w-3.5" />, cls: "text-destructive", label: t("failed") },
  };
  const style = states[update?.state ?? "unchecked"];
  return (
    <div className="min-w-0">
      <span className={`inline-flex items-center gap-1 font-medium ${style.cls}`} title={update?.detail || undefined}>
        {style.icon}
        {style.label}
      </span>
      {update?.state === "available" ? (
        <div className="text-muted-foreground">
          <Rev rev={update.available_rev} at={update.available_at} locale={locale} />
          <button
            type="button"
            onClick={onApply}
            disabled={applying}
            className="mt-1 flex items-center gap-1.5 rounded-md bg-primary px-2 py-0.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {applying ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ArrowUpCircle className="h-3.5 w-3.5" />}
            {applying ? t("applying") : t("apply")}
          </button>
        </div>
      ) : null}
      {update?.state === "outdated" ? <p className="mt-0.5 break-words text-muted-foreground">{update.detail}</p> : null}
    </div>
  );
}

/** Every skill skills/flake.nix lists: where it comes from, what is locked, and whether something newer is there. */
export function SkillSourcesPanel({ server }: { server: string }) {
  const t = useTranslations("knowledge.skillSources");
  const locale = useLocale();
  const [sources, setSources] = useState<KnowledgeSkillSources | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [applying, setApplying] = useState<string | null>(null);
  const [config, setConfig] = useState<KnowledgeSkillsConfig | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchSkillsConfig(server)
      .then((next) => !cancelled && setConfig(next))
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : String(err)));
    return () => {
      cancelled = true;
    };
  }, [server]);

  // A saved change is evaluated again: follow it, so Nix's verdict on the values shows up here.
  useEffect(() => {
    if (!config?.skills.some((skill) => skill.state === "building")) return;
    const timer = window.setTimeout(async () => {
      try {
        setConfig(await fetchSkillsConfig(server));
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    }, POLL_MS);
    return () => window.clearTimeout(timer);
  }, [config, server]);

  async function save(
    name: string,
    enable: boolean,
    settings: Record<string, SkillConfigValue | null>,
    credentials: Record<string, string | null>,
  ) {
    if (!config) return;
    setError(null);
    setSaving(name);
    try {
      setConfig(await saveSkillConfig(server, name, { base: config.base, enable, settings, credentials }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(null);
    }
  }

  useEffect(() => {
    let cancelled = false;
    fetchSkillSources(server)
      .then((next) => !cancelled && setSources(next))
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : String(err)));
    return () => {
      cancelled = true;
    };
  }, [server]);

  // A check fetches from every upstream; follow it until it is done.
  useEffect(() => {
    if (!sources?.checking) return;
    const timer = window.setTimeout(async () => {
      try {
        setSources(await fetchSkillSources(server));
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    }, POLL_MS);
    return () => window.clearTimeout(timer);
  }, [sources, server]);

  async function check() {
    setError(null);
    try {
      setSources(await checkSkillUpdates(server));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function apply(name: string) {
    setError(null);
    setApplying(name);
    try {
      setSources(await applySkillUpdate(server, name));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setApplying(null);
    }
  }

  if (!sources) return error ? <p className="text-sm text-destructive">{error}</p> : null;
  return (
    <section className="rounded-lg bg-surface p-4 text-sm">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h2 className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <GitBranch className="h-3.5 w-3.5" />
          {t("title")}
        </h2>
        <span className="text-xs text-muted-foreground" title={sources.checked_at ? formatAbsoluteTime(sources.checked_at, locale) : undefined}>
          {sources.checked_at ? t("checkedAt", { date: formatAbsoluteTime(sources.checked_at, locale) }) : t("neverChecked")}
        </span>
        <button
          type="button"
          onClick={check}
          disabled={sources.checking}
          className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs font-medium transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
        >
          {sources.checking ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          {sources.checking ? t("checking") : t("check")}
        </button>
      </div>
      {sources.check_error ? <p className="mt-2 text-xs text-destructive">{sources.check_error}</p> : null}
      {error ? <p className="mt-2 text-xs text-destructive">{error}</p> : null}
      <table className="mt-3 w-full text-left text-xs">
        <thead className="text-muted-foreground">
          <tr className="border-b border-border">
            <th className="py-1.5 pr-3 font-medium">{t("columns.skill")}</th>
            <th className="w-2/5 py-1.5 font-medium">{t("columns.update")}</th>
          </tr>
        </thead>
        <tbody>
          {sources.skills.map((skill) => {
            const skillConfig = config?.skills.find((entry) => entry.name === skill.name);
            const needsConfig = skillConfig?.settings?.some((setting) => setting.missing) ?? false;
            // Every declared slot is needed by some command, so an unbound one refuses part of the skill.
            const unbound = skillConfig?.credentials?.some((slot) => slot.binding === null) ?? false;
            return (
              <Fragment key={skill.name}>
                <tr className="border-b border-border/60 align-top last:border-0">
                  <td className="py-2 pr-3">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 font-medium">
                      {skill.path ? (
                        <Link href={knowledgeBrowseHref(skill.path)} className="underline-offset-2 hover:underline">
                          {skill.name}
                        </Link>
                      ) : (
                        skill.name
                      )}
                      {skillConfig && !skillConfig.enabled ? (
                        <span className="rounded bg-muted px-1.5 text-[11px] font-normal text-muted-foreground">{t("off")}</span>
                      ) : null}
                      {needsConfig ? (
                        <span className="inline-flex items-center gap-1 text-[11px] font-normal text-warning">
                          <CircleAlert className="h-3 w-3" />
                          {t("needsConfig")}
                        </span>
                      ) : null}
                      {unbound ? (
                        <span className="inline-flex items-center gap-1 text-[11px] font-normal text-warning">
                          <CircleAlert className="h-3 w-3" />
                          {t("credentialUnbound")}
                        </span>
                      ) : null}
                      {skillConfig ? (
                        <button
                          type="button"
                          aria-expanded={open === skill.name}
                          onClick={() => setOpen(open === skill.name ? null : skill.name)}
                          className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-normal text-muted-foreground hover:bg-muted"
                        >
                          <SlidersHorizontal className="h-3 w-3" />
                          {t("configure")}
                        </button>
                      ) : null}
                    </div>
                    {/* Origin and what is locked under the name, so the verdict keeps its column on a phone. */}
                    <code className="mt-0.5 block break-all font-mono text-muted-foreground" title={t("columns.origin")}>
                      {skill.origin}
                    </code>
                    <div className="mt-0.5 text-muted-foreground" title={t("columns.locked")}>
                      {skill.path ? t("local") : <Rev rev={skill.locked_rev} at={skill.locked_at} locale={locale} />}
                    </div>
                  </td>
                  <td className="py-2">
                    <UpdateCell
                      skill={skill}
                      locale={locale}
                      applying={applying !== null}
                      onApply={() => apply(skill.name)}
                    />
                  </td>
                </tr>
                {open === skill.name && skillConfig && config ? (
                  <tr className="border-b border-border/60">
                    <td colSpan={2} className="pb-3">
                      {/* Keyed by config.json's version: a save, or anyone's commit, starts the form afresh. */}
                      <SkillConfigForm
                        server={server}
                        key={config.base}
                        skill={skillConfig}
                        saving={saving === skill.name}
                        onSave={(enable, settings, credentials) => save(skill.name, enable, settings, credentials)}
                      />
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
