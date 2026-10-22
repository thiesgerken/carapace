"use client";

import {
  BookText,
  Cable,
  CircleAlert,
  CircleDashed,
  Check,
  ChevronRight,
  Copy,
  Download,
  GitCommitHorizontal,
  Globe,
  KeyRound,
  Lightbulb,
  Loader2,
  Plug,
  Puzzle,
  Terminal,
  X,
} from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";

import { useAppShell } from "@/components/app-shell-context";
import { ArtifactPreview } from "@/components/artifact-preview";
import { useAppLocale } from "@/components/locale-provider";
import { GlobalGitPanel, KNOWLEDGE_GIT_CHANGED_EVENT, useGlobalGit } from "@/components/git-sync";
import { MarkdownContent } from "@/components/markdown-content";
import {
  browseKnowledge,
  knowledgeArtifactUrl,
  knowledgeRawUrl,
  type KnowledgeBrowseResult,
  type KnowledgeEntry,
  type KnowledgeFileInfo,
  type KnowledgeSkill,
} from "@/lib/api";
import { useBrand } from "@/hooks/use-brand";
import { entryIcon } from "@/lib/file-icons";
import { formatAbsoluteTime, formatRelativeTime } from "@/lib/format-time";
import { knowledgeBrowseHref } from "@/lib/knowledge-links";
import { fencedCodeBlock, languageFromFilePath } from "@/lib/sandbox-read";
import { cn, formatBytes } from "@/lib/utils";

function isMarkdown(name: string): boolean {
  return /\.(md|markdown)$/i.test(name);
}

function Breadcrumb({ path, rootLabel }: { path: string; rootLabel: string }) {
  const segments = path ? path.split("/") : [];
  return (
    <nav aria-label={rootLabel} className="flex min-w-0 flex-wrap items-center gap-1 text-sm">
      <Link
        href={knowledgeBrowseHref("")}
        className="shrink-0 rounded-sm font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {rootLabel}
      </Link>
      {segments.map((segment, index) => {
        const segmentPath = segments.slice(0, index + 1).join("/");
        const last = index === segments.length - 1;
        return (
          <span key={segmentPath} className="flex min-w-0 items-center gap-1">
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60" />
            {last ? (
              <span className="truncate font-medium text-foreground">{segment}</span>
            ) : (
              <Link
                href={knowledgeBrowseHref(segmentPath)}
                className="truncate rounded-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {segment}
              </Link>
            )}
          </span>
        );
      })}
    </nav>
  );
}

function rowIcon(entry: KnowledgeEntry): ReactNode {
  return entryIcon(
    { name: entry.name, type: entry.type, kind: entry.kind },
    cn("h-4 w-4 shrink-0", entry.type === "dir" ? "text-accent-foreground/70" : "text-muted-foreground"),
  );
}

/** Short hash that copies the full one — what a reader actually needs to paste. */
function CopyHash({
  commit,
  copyLabel,
  copiedLabel,
}: {
  commit: NonNullable<KnowledgeEntry["commit"]>;
  copyLabel: string;
  copiedLabel: string;
}) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(timer);
  }, [copied]);

  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(commit.hash);
      setCopied(true);
    } catch {
      // Clipboard denied (insecure origin, or the user said no) — leave the label alone.
    }
  }

  return (
    <button
      type="button"
      onClick={() => void copy()}
      title={copied ? copiedLabel : `${copyLabel}: ${commit.hash}`}
      aria-label={copied ? copiedLabel : `${copyLabel}: ${commit.hash}`}
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-sm font-mono transition-colors",
        "hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        copied && "text-foreground",
      )}
    >
      {commit.short}
      {copied ? (
        <Check className="h-3 w-3 shrink-0" />
      ) : (
        <Copy className="h-3 w-3 shrink-0 opacity-0 transition-opacity group-hover/commit:opacity-60" />
      )}
    </button>
  );
}

/**
 * One row in a directory listing. The row links into the repo; recognized kinds add
 * a trailing link of their own (a session's title opens the chat), so the row is a
 * container rather than a single anchor — anchors cannot nest.
 */
function EntryRow({
  path,
  entry,
  untitledLabel,
  justNowLabel,
  copyHashLabel,
  copiedLabel,
  locale,
  now,
}: {
  path: string;
  entry: KnowledgeEntry;
  untitledLabel: string;
  justNowLabel: string;
  copyHashLabel: string;
  copiedLabel: string;
  locale: string;
  now: number;
}) {
  const entryPath = path ? `${path}/${entry.name}` : entry.name;
  const tArtifacts = useTranslations("artifacts");
  // The commit date is what a reader means by "last changed"; mtime only fills in for
  // paths no commit covers, since a checkout rewrites it.
  const changedAt = entry.commit?.committed_at ?? entry.modified;
  return (
    <div className="flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition-colors hover:bg-muted">
      {rowIcon(entry)}
      <Link
        href={knowledgeBrowseHref(entryPath)}
        className="min-w-0 flex-1 truncate rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {entry.name}
      </Link>
      {entry.kind === "artifact" && entry.shared && <span className="shrink-0 rounded border border-teal-600/30 px-1.5 py-0.5 text-xs text-teal-600 dark:text-teal-400">{tArtifacts("shared")}</span>}
      {/* Flexible middle column, the first thing to go as the row narrows: the session
          title where there is one, the commit otherwise. A session's commit subject
          only ever restates the archiving, so the title is the better use of it. */}
      {entry.session_id ? (
        <Link
          href={`/?session=${encodeURIComponent(entry.session_id)}`}
          title={entry.label ?? undefined}
          className="hidden min-w-0 max-w-[40%] shrink basis-[40%] truncate rounded-sm text-xs text-muted-foreground underline-offset-2 transition-colors hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring lg:block"
        >
          {entry.label ?? untitledLabel}
        </Link>
      ) : entry.kind === "artifact" && entry.label ? (
        <span
          title={entry.label}
          className="hidden min-w-0 max-w-[40%] shrink basis-[40%] truncate text-xs text-muted-foreground lg:block"
        >
          {entry.label}
        </span>
      ) : entry.commit ? (
        <span className="group/commit hidden min-w-0 max-w-[40%] shrink basis-[40%] items-baseline gap-2 text-xs text-muted-foreground lg:flex">
          <CopyHash commit={entry.commit} copyLabel={copyHashLabel} copiedLabel={copiedLabel} />
          <span className="truncate" title={entry.commit.subject}>
            {entry.commit.subject}
          </span>
        </span>
      ) : null}
      {/* Both slots keep their width when empty, so directories (no size) line up
          with files instead of shifting the whole row right. */}
      <span className="flex shrink-0 items-baseline gap-2 text-xs tabular-nums text-muted-foreground">
        <span
          className="hidden w-28 truncate text-right sm:block"
          title={changedAt ? formatAbsoluteTime(changedAt, locale) : undefined}
        >
          {changedAt ? formatRelativeTime(changedAt, locale, now, justNowLabel) : null}
        </span>
        <span className="w-16 text-right">{entry.size != null ? formatBytes(entry.size) : null}</span>
      </span>
    </div>
  );
}

function SkillSection({ icon, label, children }: { icon: ReactNode; label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1 sm:flex-row sm:gap-3">
      {/* self-start: the label row must not stretch, or items-center drifts it to the
          vertical middle of a multi-line value list. */}
      <div className="flex shrink-0 items-center gap-1.5 self-start pt-0.5 text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground sm:w-32">
        {icon}
        {label}
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-1">{children}</div>
    </div>
  );
}

const sectionIconClass = "h-3.5 w-3.5 shrink-0";

/** Frontmatter of a skill's SKILL.md as a card: what it exposes, reaches, and needs. */
function VaultBadge({ status }: { status?: string }) {
  const t = useTranslations("knowledge.skill");
  if (!status) return null;
  const map: Record<string, { icon: ReactNode; cls: string; label: string }> = {
    present: { icon: <Check className="h-3 w-3" />, cls: "text-emerald-600 dark:text-emerald-400", label: t("vaultPresent") },
    absent: { icon: <X className="h-3 w-3" />, cls: "text-red-600 dark:text-red-400", label: t("vaultAbsent") },
    unconfigured: { icon: <CircleDashed className="h-3 w-3" />, cls: "text-muted-foreground", label: t("vaultUnconfigured") },
    error: { icon: <CircleAlert className="h-3 w-3" />, cls: "text-muted-foreground", label: t("vaultError") },
  };
  const s = map[status] ?? map.error;
  return (
    <span className={`inline-flex items-center gap-0.5 text-[10px] ${s.cls}`} title={s.label}>
      {s.icon}
    </span>
  );
}

function SkillCard({ skill, vaultStatus }: { skill: KnowledgeSkill; vaultStatus?: Record<string, string> }) {
  const t = useTranslations("knowledge.skill");
  const carapace = skill.carapace;
  const domains = carapace?.network.domains ?? [];
  const tunnels = carapace?.network.tunnels ?? [];
  const credentials = carapace?.credentials ?? [];
  const commands = carapace?.commands ?? [];
  const mcpServers = carapace?.mcp ?? [];
  const hints = Object.entries(carapace?.hints ?? {});

  return (
    <section className="rounded-lg border border-border bg-muted/30 p-4">
      <div className="flex items-baseline gap-2">
        <Puzzle className="h-4 w-4 shrink-0 self-center text-accent-foreground/70" />
        <h2 className="min-w-0 break-all font-mono text-sm font-semibold">{skill.name}</h2>
      </div>
      {skill.description ? (
        <p className="mt-1.5 text-sm text-muted-foreground">{skill.description}</p>
      ) : null}

      {commands.length || domains.length || tunnels.length || credentials.length || mcpServers.length || hints.length ? (
        <div className="mt-4 flex flex-col gap-3 border-t border-border/70 pt-3 text-sm">
          {commands.length ? (
            <SkillSection icon={<Terminal className={sectionIconClass} />} label={t("commands")}>
              {commands.map((command) => (
                <div key={command.name} className="flex min-w-0 flex-col gap-0.5">
                  <code className="break-all font-mono text-xs font-semibold">{command.name}</code>
                  <code className="break-all font-mono text-xs text-muted-foreground">{command.command}</code>
                </div>
              ))}
            </SkillSection>
          ) : null}

          {domains.length ? (
            <SkillSection icon={<Globe className={sectionIconClass} />} label={t("domains")}>
              {domains.map((domain) => (
                <code key={domain} className="break-all font-mono text-xs">{domain}</code>
              ))}
            </SkillSection>
          ) : null}

          {tunnels.length ? (
            <SkillSection icon={<Cable className={sectionIconClass} />} label={t("tunnels")}>
              {tunnels.map((tunnel) => (
                <div key={`${tunnel.host}:${tunnel.remote_port}`} className="min-w-0">
                  <code className="break-all font-mono text-xs">
                    localhost:{tunnel.local_port} → {tunnel.host}:{tunnel.remote_port}
                  </code>
                  {tunnel.description ? (
                    <span className="ml-2 break-words text-xs text-muted-foreground">{tunnel.description}</span>
                  ) : null}
                </div>
              ))}
            </SkillSection>
          ) : null}

          {credentials.length ? (
            <SkillSection icon={<KeyRound className={sectionIconClass} />} label={t("credentials")}>
              {credentials.map((credential) => (
                <div key={credential.vault_path} className="flex min-w-0 flex-col gap-0.5">
                  <div className="flex min-w-0 flex-wrap items-baseline gap-x-2">
                    <code className="break-all font-mono text-xs font-semibold">
                      {credential.env_var ?? credential.file ?? t("credential")}
                    </code>
                    {credential.description ? (
                      <span className="break-words text-xs text-muted-foreground">{credential.description}</span>
                    ) : null}
                  </div>
                  <div className="flex min-w-0 items-center gap-1">
                    <code className="break-all font-mono text-xs text-muted-foreground">{credential.vault_path}</code>
                    <VaultBadge status={vaultStatus?.[credential.vault_path]} />
                  </div>
                </div>
              ))}
            </SkillSection>
          ) : null}

          {mcpServers.length ? (
            <SkillSection icon={<Plug className={sectionIconClass} />} label={t("mcp")}>
              {mcpServers.map((server) => (
                <div key={server.name} className="flex min-w-0 flex-col gap-0.5">
                  <div className="flex min-w-0 flex-wrap items-baseline gap-x-2">
                    <code className="break-all font-mono text-xs font-semibold">{server.name}</code>
                    {server.description ? (
                      <span className="break-words text-xs text-muted-foreground">{server.description}</span>
                    ) : null}
                  </div>
                  <code className="break-all font-mono text-xs text-muted-foreground">
                    {server.command ? `stdio: ${server.command}` : server.url}
                  </code>
                  {server.auth ? (
                    <div className="flex min-w-0 items-center gap-1">
                      <code className="break-all font-mono text-xs text-muted-foreground">
                        {t("mcpAuth", { type: server.auth.type })} · {server.auth.vault_path}
                      </code>
                      <VaultBadge status={vaultStatus?.[server.auth.vault_path]} />
                    </div>
                  ) : null}
                  {server.auth?.type === "oauth" && vaultStatus?.[server.auth.vault_path] !== "present" ? (
                    <p className="mt-0.5 text-[11px] text-muted-foreground">
                      {t("oauthHint")}{" "}
                      <code className="break-all font-mono">
                        python scripts/mcp_oauth_blob.py --token-url … --client-id … --refresh-token …
                      </code>{" "}
                      {t("oauthHintStore")}
                    </p>
                  ) : null}
                </div>
              ))}
            </SkillSection>
          ) : null}

          {hints.length ? (
            <SkillSection icon={<Lightbulb className={sectionIconClass} />} label={t("hints")}>
              {hints.map(([key, value]) => (
                <div key={key} className="min-w-0 break-words text-xs">
                  <code className="break-all font-mono font-semibold">{key}</code>
                  <span className="ml-2 text-muted-foreground">{value}</span>
                </div>
              ))}
            </SkillSection>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

const MAX_HIGHLIGHTED_CHARS = 128 * 1024;

// Kept in step with INLINE_MIME_TYPES on the server, which serves everything else as
// an attachment — an <img> pointing at those would just break. SVG is not among them:
// it carries script, and repo contents come from a sandboxed agent's push.
const INLINE_IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/gif", "image/webp", "image/avif"]);

// MAX_INLINE_TEXT_BYTES on the server: past it, contents are not sent at all.
const MAX_INLINE_BYTES = 1024 * 1024;

function FileContent({
  server,
  file,
  noPreviewLabel,
  largeFileLabel,
  tooLargeLabel,
}: {
  server: string;
  file: KnowledgeFileInfo;
  noPreviewLabel: string;
  largeFileLabel: string;
  tooLargeLabel: string;
}) {
  if (INLINE_IMAGE_TYPES.has(file.mime)) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={knowledgeRawUrl(server, file.path)}
        alt={file.name}
        className="max-w-full rounded-lg border border-border"
      />
    );
  }
  // The server inlines contents for anything that decodes as text, so extensionless
  // files (.gitignore, Dockerfile) still render; only binaries fall through.
  if (file.content != null) {
    // Both renderers tokenize the whole document up front, which locks the tab on a
    // large one — session archives run to hundreds of KB. Plain text past the
    // threshold, markdown included: a big README goes through the same Shiki pass.
    if (file.content.length > MAX_HIGHLIGHTED_CHARS) {
      return (
        <div className="flex flex-col gap-2">
          <p className="text-xs text-muted-foreground">{largeFileLabel}</p>
          <pre className="overflow-x-auto rounded-lg border border-border bg-muted/30 p-3 font-mono text-xs leading-relaxed">
            {file.content}
          </pre>
        </div>
      );
    }
    if (isMarkdown(file.name)) {
      return <MarkdownContent content={file.content} />;
    }
    return <MarkdownContent content={fencedCodeBlock(languageFromFilePath(file.name), file.content)} />;
  }
  // The server also returns no content for a file past its inline cap, which is not
  // the same thing as an unsupported type — say which one it is.
  return (
    <p className="text-sm text-muted-foreground">
      {file.size > MAX_INLINE_BYTES ? tooLargeLabel : noPreviewLabel}
    </p>
  );
}

export function KnowledgeView() {
  const t = useTranslations("knowledge");
  const { name: brand } = useBrand();
  const tSidebar = useTranslations("sidebar");
  const { locale } = useAppLocale();
  const { server, token } = useAppShell();
  const git = useGlobalGit(server, token);
  const searchParams = useSearchParams();
  const path = (searchParams.get("path") ?? "").replace(/^\/+|\/+$/g, "");

  const [result, setResult] = useState<KnowledgeBrowseResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Reference point for relative times, refreshed whenever a listing loads. No ticking
  // timer: rows are re-read on every navigation, so drift only shows on an idle page.
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    document.title = `${t("title")} • ${brand}`;
  }, [t, brand]);

  // Bumped to force a re-browse of the same path after a pull/push moves the repo.
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    const onGitChanged = () => setReloadToken((token) => token + 1);
    window.addEventListener(KNOWLEDGE_GIT_CHANGED_EVENT, onGitChanged);
    return () => window.removeEventListener(KNOWLEDGE_GIT_CHANGED_EVENT, onGitChanged);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const browsed = await browseKnowledge(server, path);
        if (!cancelled) {
          setResult(browsed);
          setNow(Date.now());
        }
      } catch (browseError) {
        if (!cancelled) {
          setResult(null);
          setError(browseError instanceof Error ? browseError.message : t("error"));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [server, path, t, reloadToken]);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="mx-auto w-full max-w-3xl px-5 py-5 sm:px-6">
        <div className="pb-4">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
              {git.head ? (
                <div className="mt-1.5 flex min-w-0 items-baseline gap-2 text-xs text-muted-foreground">
                  <GitCommitHorizontal className="h-3.5 w-3.5 shrink-0 self-center" />
                  <span className="shrink-0 font-mono">{git.head.hash}</span>
                  <span className="truncate" title={git.head.subject}>{git.head.subject}</span>
                </div>
              ) : null}
            </div>
            <GlobalGitPanel git={git} alwaysShow className="w-56 shrink-0" />
          </div>

          <div className="mt-4 flex items-center justify-between gap-3 border-t border-border/70 pt-3">
            <Breadcrumb path={path} rootLabel={t("root")} />
            {/* While a new path loads, `result` still holds the previous one — showing
                its download button would offer the file the user just navigated away
                from. */}
            {!loading && result?.type === "file" ? (
              <a
                href={knowledgeRawUrl(server, result.path, { download: true })}
                title={t("download")}
                aria-label={t("download")}
                className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <Download className="h-4 w-4" />
              </a>
            ) : null}
          </div>
        </div>

        {loading ? (
          <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t("loading")}
          </div>
        ) : error ? (
          <p className="py-8 text-sm text-destructive">{error}</p>
        ) : result?.artifact ? (
          <ArtifactPreview
            key={`${result.path}:${reloadToken}`}
            src={knowledgeArtifactUrl(server, result.artifact.slug)}
            sourceUrl={knowledgeRawUrl(server, `artifacts/${result.artifact.slug}/index.html`)}
            title={result.artifact.title}
            artifact={{ server, ...result.artifact }}
          />
        ) : result?.type === "dir" ? (
          <>
            {result.entries.length === 0 ? (
              <p className="py-8 text-sm text-muted-foreground">{t("empty")}</p>
            ) : (
              <div className="flex flex-col gap-0.5 rounded-lg border border-border p-1.5">
                {result.entries.map((entry) => (
                  <EntryRow
                    key={entry.name}
                    path={result.path}
                    entry={entry}
                    untitledLabel={t("untitledSession")}
                    justNowLabel={tSidebar("time.justNow")}
                    copyHashLabel={t("copyHash")}
                    copiedLabel={t("copiedHash")}
                    locale={locale}
                    now={now}
                  />
                ))}
              </div>
            )}
            {result.skill ? <div className="mt-6"><SkillCard skill={result.skill} vaultStatus={result.vault_status} /></div> : null}
            {result.doc ? (
              <section className="mt-6">
                <h2 className="mb-2 flex items-center gap-1.5 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
                  <BookText className="h-3.5 w-3.5" />
                  {result.doc_name}
                </h2>
                <MarkdownContent content={result.doc} />
              </section>
            ) : null}
          </>
        ) : result?.type === "file" ? (
          <FileContent
            key={`${result.path}:${reloadToken}`}
            server={server}
            file={result}
            noPreviewLabel={t("noPreview")}
            largeFileLabel={t("largeFileNotice")}
            tooLargeLabel={t("tooLarge")}
          />
        ) : null}
      </div>
    </div>
  );
}
