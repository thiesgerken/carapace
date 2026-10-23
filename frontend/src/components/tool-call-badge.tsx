"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import {
  Archive,
  ChevronRight,
  ExternalLink,
  FileText,
  FilePen,
  FolderCode,
  GitBranch,
  Globe,
  KeyRound,
  Loader2,
  Plug,
  Puzzle,
  Replace,
  Send,
  ShieldAlert,
  ShieldCheck,
  SquareTerminal,
  UserCheck,
  UserX,
  Zap,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { diffLines } from "diff";
import { MarkdownContent } from "./markdown-content";
import { FilePreview } from "./file-preview";
import {
  fencedCodeBlock,
  languageFromFilePath,
  splitReadToolResult,
} from "@/lib/sandbox-read";
import type { CompactionAnnotation, SentFile } from "@/lib/types";
import { cn } from "@/lib/utils";
import { sentFileUrl } from "@/lib/api";
import { artifactSnapshotTitle, artifactViewerHref, sentArtifactSlug } from "@/lib/artifacts";

interface ToolCallBadgeProps {
  tool: string;
  args: Record<string, unknown>;
  detail: string;
  contexts?: string[];
  approvalSource?: ApprovalSource;
  approvalVerdict?: ApprovalVerdict;
  approvalExplanation?: string;
  decisionMessage?: string;
  result?: string;
  files?: SentFile[];
  exitCode?: number;
  loading?: boolean;
  compaction?: CompactionAnnotation;
  childCalls?: ToolCallBadgeProps[];
  server?: string;
  sessionId?: string;
}

type ApprovalSource = "safe-list" | "sentinel" | "user" | "skill" | "bypass" | "unknown";
type ApprovalVerdict = "allow" | "deny" | "escalate";

const TOOL_ICONS: Record<string, LucideIcon> = {
  exec: SquareTerminal,
  read: FileText,
  write: FilePen,
  str_replace: Replace,
  use_skill: Puzzle,
  credential_access: KeyRound,
  proxy_domain: Globe,
  git_push: GitBranch,
  send_file: Send,
};

const SHORT_KEYS: Record<string, string> = {
  command: "cmd",
  filename: "file",
  directory: "dir",
};

/** Arg keys shown without `key=` when the tool name already implies them. */
const OMIT_ARG_LABEL: Record<string, ReadonlySet<string>> = {
  exec: new Set(["command"]),
  read: new Set(["path"]),
  use_skill: new Set(["skill_name"]),
};

const MAX_SUMMARY_VALUE_CHARS = 4096;
const MULTILINE_SUMMARY_THRESHOLD = 96;

type TranslateFn = (
  key: string,
  values?: Record<string, string | number>,
) => string;

function stringArg(args: Record<string, unknown>, key: string): string {
  const v = args[key];
  return typeof v === "string" ? v : "";
}

function boolArg(
  args: Record<string, unknown>,
  key: string,
): boolean | undefined {
  const v = args[key];
  return typeof v === "boolean" ? v : undefined;
}

function intArg(
  args: Record<string, unknown>,
  key: string,
): number | undefined {
  const v = args[key];
  if (typeof v === "number" && Number.isFinite(v)) return Math.trunc(v);
  return undefined;
}

function lineCount(text: string): number {
  if (text.length === 0) return 0;
  return text.split("\n").length;
}

function formatReadSummary(
  args: Record<string, unknown>,
  t: TranslateFn,
): string {
  const path = stringArg(args, "path") || t("fallbacks.missingPath");
  const offset = Math.max(0, intArg(args, "offset") ?? 0);
  const limit = Math.max(1, intArg(args, "limit") ?? 100);
  if (offset === 0) {
    return t("summaries.readFirstLines", { count: limit, path });
  }
  const start = offset + 1;
  const end = offset + limit;
  return t("summaries.readLinesRange", { start, end, path });
}

function countOutputLines(body: string): number {
  const normalized = body.replace(/\n+$/, "");
  if (normalized.length === 0) return 0;
  return normalized.split("\n").length;
}

function formatReadSummaryFromSplit(
  args: Record<string, unknown>,
  path: string,
  split: ReturnType<typeof splitReadToolResult> | null,
  t: TranslateFn,
): string {
  const fallback = formatReadSummary(args, t);
  if (!split?.hasSplit) return fallback;
  const offset = Math.max(0, intArg(args, "offset") ?? 0);
  const limit = Math.max(1, intArg(args, "limit") ?? 100);
  const bodyLines = countOutputLines(split.body);

  if (offset === 0 && bodyLines < limit) return path;
  if (offset === 0) {
    return t("summaries.readFirstLines", {
      count: bodyLines || limit,
      path,
    });
  }

  if (bodyLines > 0) {
    const start = offset + 1;
    const end = offset + bodyLines;
    return t("summaries.readLinesRange", { start, end, path });
  }
  return fallback;
}

function formatWriteSummary(
  args: Record<string, unknown>,
  t: TranslateFn,
): string {
  const path = stringArg(args, "path") || t("fallbacks.missingPath");
  const contentLines = lineCount(stringArg(args, "content"));
  return t("summaries.writeLines", { count: contentLines, path });
}

function formatStrReplaceSummary(
  args: Record<string, unknown>,
  t: TranslateFn,
): string {
  const path = stringArg(args, "path") || t("fallbacks.missingPath");
  const srcLines = lineCount(stringArg(args, "old_string"));
  const dstLines = lineCount(stringArg(args, "new_string"));
  const replaceAll = boolArg(args, "replace_all");
  const lineSummary =
    srcLines === dstLines
      ? t("summaries.lineCount", { count: srcLines })
      : t("summaries.lineCountWithReplacement", {
          source: srcLines,
          replacement: dstLines,
        });
  const suffix = replaceAll ? t("summaries.allMatchesSuffix") : "";
  return t("summaries.replaceInPath", { lineSummary, path, suffix });
}

function formatCredentialAccessSummary(args: Record<string, unknown>): string {
  const vaultPath = stringArg(args, "vault_path");
  if (!vaultPath || vaultPath === "<list>") return "";
  const name = stringArg(args, "name");
  return name || vaultPath;
}

function formatProxyDomainSummary(args: Record<string, unknown>): string {
  return stringArg(args, "domain");
}

function formatArgsSummary(
  tool: string,
  args: Record<string, unknown>,
  t: TranslateFn,
): string {
  if (tool === "use_skill") return stringArg(args, "skill_name");
  if (tool === "write") return formatWriteSummary(args, t);
  if (tool === "str_replace") return formatStrReplaceSummary(args, t);
  if (tool === "credential_access") return formatCredentialAccessSummary(args);
  if (tool === "proxy_domain") return formatProxyDomainSummary(args);
  if (tool === "git_push") return stringArg(args, "ref");

  const omit = OMIT_ARG_LABEL[tool];
  const parts: string[] = [];
  for (const [k, v] of Object.entries(args)) {
    if (k === "contexts") continue;

    let vStr = typeof v === "string" ? v : JSON.stringify(v);
    if (vStr.length > MAX_SUMMARY_VALUE_CHARS) {
      vStr = vStr.slice(0, MAX_SUMMARY_VALUE_CHARS - 1) + "…";
    }
    if (omit?.has(k)) {
      parts.push(vStr);
    } else {
      const shortKey = SHORT_KEYS[k] ?? k;
      parts.push(`${shortKey}=${vStr}`);
    }
  }
  return parts.join(", ");
}

function getExecCommand(args: Record<string, unknown>): string {
  const raw = args.command;
  if (typeof raw === "string" && raw.trim().length > 0) return raw;
  return "";
}

function normalizeOptionalLabel(value: string): string {
  let trimmed = value.trim();
  if (trimmed.length === 0) return "";

  const quotePairs: ReadonlyArray<readonly [string, string]> = [
    ['"', '"'],
    ["'", "'"],
    ["`", "`"],
    ["“", "”"],
    ["‘", "’"],
  ];

  let changed = true;
  while (changed && trimmed.length >= 2) {
    changed = false;
    for (const [open, close] of quotePairs) {
      if (trimmed.startsWith(open) && trimmed.endsWith(close)) {
        trimmed = trimmed.slice(open.length, trimmed.length - close.length).trim();
        changed = true;
        break;
      }
    }
  }

  if (trimmed.length === 0) return "";
  if (/^(null|none)$/i.test(trimmed)) return "";
  return trimmed;
}

function buildShellTranscript(command: string, output?: string): string {
  const body = ["❯ " + command];
  const normalizedOutput = output?.replace(/\n+$/, "") ?? "";
  if (normalizedOutput.length > 0) body.push(normalizedOutput);
  const payload = body.join("\n");
  const fence = payload.includes("~~~") ? "~~~~" : "~~~";
  return `${fence}shell\n${payload}\n${fence}`;
}

function getUseSkillName(args: Record<string, unknown>, t: TranslateFn): string {
  const raw = args.skill_name;
  if (typeof raw === "string" && raw.trim().length > 0) return raw;
  return t("fallbacks.missingSkillName");
}

function formatUseSkillResult(result: string): string {
  const normalized = result.replace(/\n+$/, "");
  // Render YAML front matter as fenced YAML for readable syntax highlighting.
  return normalized.replace(
    /(^|\n)---\n([\s\S]*?)\n---(?=\n|$)/,
    (_m, prefix: string, yamlBody: string) =>
      `${prefix}\`\`\`yaml\n${yamlBody.trim()}\n\`\`\``,
  );
}

/** Split use_skill result into status lines and instructions body. */
function splitUseSkillResult(result: string): {
  status: string;
  instructions: string;
} {
  const marker = "\n\nInstructions:\n\n";
  const idx = result.indexOf(marker);
  if (idx === -1) return { status: result, instructions: "" };
  return {
    status: result.slice(0, idx),
    instructions: result.slice(idx + marker.length),
  };
}

function buildUnifiedDiff(oldText: string, newText: string): string {
  const changes = diffLines(oldText, newText);
  const lines: string[] = [];
  for (const change of changes) {
    const chunk = change.value.replace(/\n$/, "");
    for (const line of chunk.split("\n")) {
      if (change.added) lines.push("+ " + line);
      else if (change.removed) lines.push("- " + line);
      else lines.push("  " + line);
    }
  }
  return lines.join("\n");
}

interface ToolLabelOptions {
  tool: string;
  isCompleted: boolean;
  isReadTool: boolean;
  isWriteTool: boolean;
  isStrReplaceTool: boolean;
  isUseSkillTool: boolean;
  isExecTool: boolean;
  isCredentialAccessTool: boolean;
  isCredentialList: boolean;
  isProxyDomainTool: boolean;
  isGitPushTool: boolean;
  isSendFileTool: boolean;
  verdict?: ApprovalVerdict;
}

function resolveToolLabel(
  options: ToolLabelOptions,
  t: (key: string) => string,
): string {
  const {
    tool,
    isCompleted,
    isReadTool,
    isWriteTool,
    isStrReplaceTool,
    isUseSkillTool,
    isExecTool,
    isCredentialAccessTool,
    isCredentialList,
    isProxyDomainTool,
    isGitPushTool,
    isSendFileTool,
    verdict,
  } = options;

  if (isCompleted) {
    if (isSendFileTool) return t("labels.sentFile");
    if (isReadTool) return t("labels.read");
    if (isWriteTool) return t("labels.wrote");
    if (isStrReplaceTool) return t("labels.replaced");
    if (isUseSkillTool) return t("labels.activatedSkill");
    if (isExecTool) return t("labels.executed");
    if (isCredentialAccessTool) {
      if (isCredentialList) return t("labels.listedCredentials");
      return verdict === "deny"
        ? t("labels.credentialDenied")
        : t("labels.accessedCredential");
    }
    if (isProxyDomainTool) {
      return verdict === "deny"
        ? t("labels.domainDenied")
        : t("labels.accessedDomain");
    }
    if (isGitPushTool) return t("labels.gitPush");
    return tool;
  }

  if (isReadTool) return t("labels.readAction");
  if (isWriteTool) return t("labels.write");
  if (isUseSkillTool) return t("labels.activateSkill");
  if (isExecTool) return t("labels.execute");
  if (isCredentialAccessTool) {
    return isCredentialList
      ? t("labels.listCredentials")
      : t("labels.accessCredential");
  }
  if (isProxyDomainTool) return t("labels.accessDomain");
  if (isGitPushTool) return t("labels.gitPush");
  if (isStrReplaceTool) return t("labels.replace");
  if (isSendFileTool) return t("labels.sendFile");
  return tool;
}

function ApprovalBadge({
  source,
  verdict,
  tooltip,
}: {
  source: ApprovalSource;
  verdict?: ApprovalVerdict;
  tooltip?: string;
}) {
  const t = useTranslations("toolCallBadge.approvalBadge");

  if (source === "safe-list") {
    return (
      <span
        className="inline-flex shrink-0 items-center text-blue-600 dark:text-blue-400"
        title={tooltip || undefined}
      >
        <ShieldCheck className="h-3 w-3" />
      </span>
    );
  }

  if (source === "sentinel") {
    if (verdict == null) {
      return (
        <span
          className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-medium bg-slate-500/10 text-slate-600 dark:text-slate-400"
          title={tooltip || undefined}
        >
          <Loader2 className="h-2.5 w-2.5 animate-spin" />
          {t("review")}
        </span>
      );
    }
    const colorClass =
      verdict === "allow"
        ? "text-green-600 dark:text-green-400"
        : verdict === "deny"
          ? "text-red-600 dark:text-red-400"
          : "text-yellow-600 dark:text-yellow-400";
    return (
      <span
        className={cn("inline-flex shrink-0 items-center", colorClass)}
        title={tooltip || undefined}
      >
        <ShieldAlert className="h-3 w-3" />
      </span>
    );
  }

  if (source === "user") {
    const isDenied = verdict === "deny";
    return (
      <span
        className={cn(
          "inline-flex shrink-0 items-center",
          isDenied
            ? "text-red-600 dark:text-red-400"
            : "text-purple-600 dark:text-purple-400",
        )}
        title={tooltip || undefined}
      >
        {isDenied ? (
          <UserX className="h-3 w-3" />
        ) : (
          <UserCheck className="h-3 w-3" />
        )}
      </span>
    );
  }

  if (source === "skill") {
    return (
      <span className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-medium bg-teal-500/10 text-teal-600 dark:text-teal-400">
        <Puzzle className="h-2.5 w-2.5" />
        {t("skill")}
      </span>
    );
  }

  if (source === "bypass") {
    return (
      <span className="inline-flex items-center gap-0.5 rounded border border-amber-300/60 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:border-amber-400/30 dark:text-amber-300">
        <Zap className="h-2.5 w-2.5" />
        {t("bypass")}
      </span>
    );
  }

  if (verdict === "deny") {
    return (
      <span className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-medium bg-red-500/10 text-red-600 dark:text-red-400">
        <ShieldAlert className="h-2.5 w-2.5" />
        {t("denied")}
      </span>
    );
  }

  return null;
}

export function ToolCallBadge({
  tool,
  args,
  detail: _detail,
  contexts,
  approvalSource,
  approvalVerdict,
  approvalExplanation,
  decisionMessage,
  result,
  files,
  exitCode,
  loading,
  compaction,
  childCalls,
  server,
  sessionId,
}: ToolCallBadgeProps) {
  const t = useTranslations("toolCallBadge");
  const tc = useTranslations("compaction");
  const ta = useTranslations("artifacts");
  const isSendFileTool = tool === "send_file";
  const artifactSlug = isSendFileTool ? sentArtifactSlug(args.path) : null;
  const [open, setOpen] = useState(isSendFileTool && artifactSlug === null);
  const [skillInstructionsOpen, setSkillInstructionsOpen] = useState(false);
  const sentFileId = files?.[0]?.file_id;
  const artifactSource = artifactSlug !== null && sentFileId && server !== undefined && sessionId !== undefined
    ? sentFileUrl(server, sessionId, sentFileId)
    : null;
  const [snapshotTitle, setSnapshotTitle] = useState<{ source: string; title: string } | null>(null);

  useEffect(() => {
    if (artifactSlug === null || artifactSource === null) return;
    const controller = new AbortController();
    async function loadTitle(source: string, slug: string) {
      try {
        const response = await fetch(source, { signal: controller.signal });
        if (!response.ok) throw new Error(`Failed to load artifact snapshot: ${response.status}`);
        const html = await response.text();
        const title = artifactSnapshotTitle(html, slug);
        if (!controller.signal.aborted) setSnapshotTitle({ source, title });
      } catch (error) {
        if (!controller.signal.aborted) console.error("Failed to load artifact snapshot title", error);
      }
    }
    void loadTitle(artifactSource, artifactSlug);
    return () => controller.abort();
  }, [artifactSlug, artifactSource]);
  void _detail;
  const source = approvalSource;
  const verdict = approvalVerdict;
  const explanation = approvalExplanation ?? "";
  const hasExplicitDecisionMessage = decisionMessage !== undefined;
  const isSentinelReviewPending = source === "sentinel" && verdict == null;
  const sentinelExplanation =
    ((source === "sentinel" && verdict != null) || hasExplicitDecisionMessage)
      ? explanation
      : "";
  const finalDecisionMessage = hasExplicitDecisionMessage
    ? decisionMessage ?? ""
    : source === "user"
      ? explanation
      : "";
  const showUserDecision =
    source === "user" && (verdict === "deny" || finalDecisionMessage.length > 0);
  const isError = exitCode != null && exitCode !== 0;
  const isExecTool = tool === "exec";
  const isUseSkillTool = tool === "use_skill";
  const isReadTool = tool === "read";
  const isWriteTool = tool === "write";
  const isStrReplaceTool = tool === "str_replace";
  const isCredentialAccessTool = tool === "credential_access";
  const isProxyDomainTool = tool === "proxy_domain";
  const isGitPushTool = tool === "git_push";
  // Skill-declared MCP tool calls arrive as `mcp:<server>:<tool>`; the server and
  // tool are also mirrored into args by the backend gate.
  const isMcpTool = tool.startsWith("mcp:");
  const mcpParts = isMcpTool ? tool.split(":") : [];
  const mcpServer = isMcpTool ? stringArg(args, "server") || mcpParts[1] || "" : "";
  const mcpTool = isMcpTool ? stringArg(args, "tool") || mcpParts.slice(2).join(":") : "";
  const isAuxiliaryTool = isCredentialAccessTool || isProxyDomainTool || isGitPushTool;
  const readPath = isReadTool && typeof args.path === "string" ? args.path : "";
  const readSplit =
    isReadTool && result != null ? splitReadToolResult(result) : null;
  const readBodyMarkdown =
    readSplit?.hasSplit === true
      ? fencedCodeBlock(languageFromFilePath(readPath), readSplit.body)
      : "";
  const execCommand = isExecTool ? getExecCommand(args) : "";
  const execTitle = isExecTool
    ? normalizeOptionalLabel(stringArg(args, "title"))
    : "";
  const execTranscript = isExecTool
    ? buildShellTranscript(execCommand || t("fallbacks.missingCommand"), result)
    : "";
  const useSkillName = isUseSkillTool ? getUseSkillName(args, t) : "";
  const useSkillSplit =
    isUseSkillTool && result != null ? splitUseSkillResult(result) : null;
  const useSkillStatus = useSkillSplit?.status ?? "";
  const useSkillInstructions =
    useSkillSplit?.instructions
      ? formatUseSkillResult(useSkillSplit.instructions)
      : "";
  const useSkillResult =
    isUseSkillTool && result != null ? formatUseSkillResult(result) : "";
  const writePath = isWriteTool ? stringArg(args, "path") : "";
  const writeContent = isWriteTool ? stringArg(args, "content") : "";
  const strReplacePath = isStrReplaceTool ? stringArg(args, "path") : "";
  const strReplaceSource = isStrReplaceTool
    ? stringArg(args, "old_string")
    : "";
  const strReplaceReplacement = isStrReplaceTool
    ? stringArg(args, "new_string")
    : "";
  const credentialAccessPath = isCredentialAccessTool
    ? stringArg(args, "vault_path")
    : "";
  const isCredentialList =
    isCredentialAccessTool &&
    (credentialAccessPath.length === 0 || credentialAccessPath === "<list>");
  const isCompleted =
    !loading && (result != null || exitCode != null || isAuxiliaryTool);
  const toolLabel = artifactSlug !== null
    ? t("labels.artifact", { title: snapshotTitle?.source === artifactSource ? snapshotTitle.title : artifactSlug })
    : isMcpTool
    ? mcpServer
      ? `${mcpServer} · ${mcpTool}`
      : mcpTool
    : resolveToolLabel(
    {
      tool,
      isCompleted,
      isReadTool,
      isWriteTool,
      isStrReplaceTool,
      isUseSkillTool,
      isExecTool,
      isCredentialAccessTool,
      isCredentialList,
      isProxyDomainTool,
      isGitPushTool,
      isSendFileTool,
      verdict,
    },
    t,
  );
  const argsSummary =
    artifactSlug !== null ? "" : isExecTool
      ? execTitle || execCommand || t("fallbacks.missingCommand")
      : isReadTool
        ? formatReadSummaryFromSplit(
            args,
            readPath || t("fallbacks.missingPath"),
            readSplit,
            t,
          )
        : isMcpTool
          ? formatArgsSummary(
              tool,
              (args.args && typeof args.args === "object" ? (args.args as Record<string, unknown>) : {}),
              t,
            )
          : formatArgsSummary(tool, args, t);
  const shouldClampSummary = argsSummary.length > MULTILINE_SUMMARY_THRESHOLD;
  const contextCount = contexts?.length ?? 0;
  const contextTooltip = contexts?.join("\n") ?? "";
  const writeLang = isWriteTool ? languageFromFilePath(writePath) : "text";
  const writeContentMarkdown = isWriteTool
    ? fencedCodeBlock(writeLang, writeContent)
    : "";
  const strReplaceLang = isStrReplaceTool
    ? languageFromFilePath(strReplacePath)
    : "text";
  const strReplaceSourceMarkdown = isStrReplaceTool
    ? fencedCodeBlock(strReplaceLang, strReplaceSource)
    : "";
  const strReplaceReplacementMarkdown = isStrReplaceTool
    ? fencedCodeBlock(strReplaceLang, strReplaceReplacement)
    : "";
  const strReplaceDiffMarkdown = isStrReplaceTool
    ? fencedCodeBlock("diff", buildUnifiedDiff(strReplaceSource, strReplaceReplacement))
    : "";

  const indicators = (
    <span className={cn("ml-auto inline-flex shrink-0 items-center gap-1.5", shouldClampSummary && "pt-0.5")}>
      {(() => {
        // Count credentials: from use_skill declared_creds + child credential_access events
        const declaredCredCount = isUseSkillTool && Array.isArray(args.declared_creds)
          ? args.declared_creds.length : 0;
        const childCredCount = childCalls?.filter(c => c.tool === "credential_access").length ?? 0;
        const credCount = declaredCredCount || childCredCount;
        const credTooltip = isUseSkillTool && Array.isArray(args.declared_creds)
          ? (args.declared_creds as Array<{ vault_path: string; name?: string }>).map(c => c.name || c.vault_path).join("\n")
          : childCalls?.filter(c => c.tool === "credential_access").map(c => {
              const name = c.args.name as string | undefined;
              const vp = c.args.vault_path as string | undefined;
              return name || vp || t("fallbacks.credential");
            }).join("\n") ?? "";

        // Count domains: from use_skill declared_domains + child proxy_domain events
        const declaredDomainCount = isUseSkillTool && Array.isArray(args.declared_domains)
          ? args.declared_domains.length : 0;
        const childDomainCount = childCalls?.filter(c => c.tool === "proxy_domain").length ?? 0;
        const domainCount = declaredDomainCount || childDomainCount;
        const domainTooltip = isUseSkillTool && Array.isArray(args.declared_domains)
          ? (args.declared_domains as string[]).join("\n")
          : childCalls?.filter(c => c.tool === "proxy_domain").map(c => c.args.domain as string ?? "").join("\n") ?? "";

        // Count MCP servers declared by use_skill
        const declaredMcp = isUseSkillTool && Array.isArray(args.declared_mcp)
          ? (args.declared_mcp as Array<{ name: string; url?: string; command?: string }>) : [];
        const mcpTooltip = declaredMcp.map(s => `${s.name} (${s.command ? `stdio: ${s.command}` : s.url})`).join("\n");

        return (
          <>
            {declaredMcp.length > 0 && (
              <span
                className="inline-flex items-center gap-0.5 rounded bg-blue-500/15 px-1.5 py-0.5 text-[10px] text-blue-600 dark:text-blue-400"
                title={mcpTooltip}
              >
                <Plug className="h-2.5 w-2.5" />{declaredMcp.length}
              </span>
            )}
            {credCount > 0 && (
              <span
                className="inline-flex items-center gap-0.5 rounded bg-blue-500/15 px-1.5 py-0.5 text-[10px] text-blue-600 dark:text-blue-400"
                title={credTooltip}
              >
                <KeyRound className="h-2.5 w-2.5" />{credCount}
              </span>
            )}
            {domainCount > 0 && (
              <span
                className="inline-flex items-center gap-0.5 rounded bg-blue-500/15 px-1.5 py-0.5 text-[10px] text-blue-600 dark:text-blue-400"
                title={domainTooltip}
              >
                <Globe className="h-2.5 w-2.5" />{domainCount}
              </span>
            )}
            {contextCount > 0 && (
              <span
                className="inline-flex items-center gap-0.5 rounded bg-teal-500/15 px-1.5 py-0.5 text-[10px] text-teal-600 dark:text-teal-400"
                title={contextTooltip}
              >
                <Puzzle className="h-2.5 w-2.5" />{contextCount}
              </span>
            )}
          </>
        );
      })()}
      {source && <ApprovalBadge source={source} verdict={verdict} tooltip={finalDecisionMessage || sentinelExplanation || undefined} />}
      {compaction?.method && (
        <span
          className="inline-flex items-center rounded bg-amber-500/15 p-0.5 text-amber-700 dark:text-amber-400"
          title={tc("toolTitle", {
            method: tc(`methods.${compaction.method}`),
            orig: compaction.orig_tokens ?? 0,
            summary: compaction.summary_tokens ?? 0,
          })}
        >
          <Archive className="h-2.5 w-2.5" />
        </span>
      )}
      {loading && (
        <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
      )}
    </span>
  );

  return (
    <div className="my-1 w-full min-w-0">
      <div className={cn(
        artifactSlug !== null && "flex items-stretch rounded-md text-muted-foreground hover:bg-accent transition-colors",
        artifactSlug !== null && open && "bg-accent",
      )}>
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          className={cn(
            "flex min-w-0 gap-1.5 rounded-md px-2 py-1 text-xs text-left",
            artifactSlug === null ? "w-full" : "pr-0",
            shouldClampSummary ? "items-start" : "items-center",
            "text-muted-foreground hover:bg-accent transition-colors",
            open && "bg-accent",
          )}
        >
          <ChevronRight
            className={cn(
              "h-3 w-3 shrink-0 transition-transform",
              open && "rotate-90",
            )}
          />
          {(() => {
            const ToolIcon = artifactSlug !== null ? FolderCode : TOOL_ICONS[tool] ?? (isMcpTool ? Plug : undefined);
            return ToolIcon ? (
              <ToolIcon className="h-3 w-3 shrink-0 text-foreground/65 dark:text-foreground/70" />
            ) : null;
          })()}
          <span className={cn("font-medium text-foreground/85 dark:text-foreground/90", artifactSlug !== null ? "min-w-0 truncate" : "shrink-0")} title={artifactSlug !== null ? toolLabel : undefined}>
            {toolLabel}
          </span>
          {argsSummary ? (
            <span
              className={cn(
                "min-w-0 flex-1 font-mono text-[11px] text-foreground/60 dark:text-foreground/65",
                shouldClampSummary
                  ? "overflow-hidden [white-space:break-spaces] break-words leading-4 [display:-webkit-box] [-webkit-box-orient:vertical] [-webkit-line-clamp:2]"
                  : "overflow-hidden text-ellipsis whitespace-pre",
              )}
              title={argsSummary}
            >
              {argsSummary}
            </span>
          ) : null}
          {artifactSlug === null && indicators}
        </button>
        {artifactSlug !== null && (
          <>
            <a
              href={artifactViewerHref(artifactSlug)}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={ta("openLiveInNewTab")}
              title={ta("openLiveInNewTab")}
              className="inline-flex shrink-0 items-center rounded-md p-1.5 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <ExternalLink className="h-3 w-3" />
            </a>
            <button
              type="button"
              tabIndex={-1}
              aria-hidden="true"
              onClick={() => setOpen(!open)}
              className="flex flex-1 items-center justify-end rounded-md py-1 pl-1.5 pr-2"
            >
              {indicators}
            </button>
          </>
        )}
      </div>

      {open && (
        <div className="tool-row-details ml-5 mt-1.5 rounded-lg border border-border/60 bg-muted/30 p-3 space-y-2 text-xs">
          {compaction?.model_text && (
            <details className="rounded-md border border-amber-500/30 bg-amber-500/5">
              <summary className="flex cursor-pointer list-none items-center gap-1 px-2 py-1 text-[11px] text-muted-foreground hover:bg-accent/50">
                <Archive className="h-3 w-3 text-amber-600/70" />
                <span className="font-medium">{tc("modelSees")}</span>
                <span className="opacity-70">
                  · {tc("tokenDelta", { from: compaction.orig_tokens ?? 0, to: compaction.summary_tokens ?? 0 })}
                </span>
              </summary>
              <div className="whitespace-pre-wrap break-words border-t border-amber-500/20 px-2 py-1.5 font-mono text-[11px] text-muted-foreground">
                {compaction.model_text}
              </div>
            </details>
          )}
          {isUseSkillTool && (
            <div className="text-muted-foreground">
              {t("details.activateSkillPromptPrefix")}{" "}
              <span className="font-mono text-foreground/85">
                {useSkillName}
              </span>{" "}
              {t("details.activateSkillPromptSuffix")}
            </div>
          )}

          {isSentinelReviewPending && (
            <div className="text-[11px] text-muted-foreground leading-relaxed">
                <span className="font-medium text-foreground/70">
                  <Loader2 className="inline h-3 w-3 -translate-y-px mr-1 animate-spin" />
                  {t("details.sentinelLabel")}
                </span>{" "}
                {t("details.sentinelReviewing")}
            </div>
          )}

          {sentinelExplanation && (
            <div className="text-[11px] text-muted-foreground leading-relaxed">
                <span className="font-medium text-foreground/70">
                  <ShieldCheck className="inline h-3 w-3 -translate-y-px mr-1" />
                  {t("details.sentinelLabel")}
                </span>{" "}
              {sentinelExplanation}
            </div>
          )}

          {showUserDecision && (
            <div className="text-[11px] text-muted-foreground leading-relaxed">
              <span className="font-medium text-foreground/70">{verdict === "deny" ? <UserX className="inline h-3 w-3 -translate-y-px mr-1" /> : <UserCheck className="inline h-3 w-3 -translate-y-px mr-1" />}{t("details.userLabel")} </span>
              {finalDecisionMessage || t("details.deniedByUser")}
            </div>
          )}

          {contexts && contexts.length > 0 && (
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="text-[11px] font-medium text-muted-foreground">{t("details.contexts")}</span>
              {contexts.map((ctx) => (
                <span
                  key={ctx}
                  className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-medium bg-teal-500/10 text-teal-600 dark:text-teal-400 font-mono"
                >
                  <Puzzle className="h-2.5 w-2.5" />
                  {ctx}
                </span>
              ))}
            </div>
          )}

          {isExecTool ? (
            <>
              {execTitle && (
                <div className="font-medium text-foreground/80">
                  {execTitle}
                </div>
              )}
              <div className={cn("exec-terminal-block")}>
                <MarkdownContent content={execTranscript} />
              </div>
            </>
          ) : isUseSkillTool ? (
            <div className="space-y-3">

              {(() => {
                const domains = (
                  Array.isArray(args.declared_domains) ? args.declared_domains : []
                ) as string[];
                return domains.length > 0 ? (
                  <div className="text-[11px] text-muted-foreground">
                    <span className="font-medium text-foreground/70"><Globe className="inline h-3 w-3 -translate-y-px mr-1" />{t("details.domains")} </span>
                    {domains.map((d, i) => (
                      <span key={d}>
                        {i > 0 && ", "}
                        <span className="font-mono">{d}</span>
                      </span>
                    ))}
                  </div>
                ) : null;
              })()}

              {(() => {
                const servers = (
                  Array.isArray(args.declared_mcp) ? args.declared_mcp : []
                ) as Array<{ name: string; url?: string; command?: string; description?: string }>;
                return servers.length > 0 ? (
                  <div className="text-[11px] text-muted-foreground">
                    <span className="font-medium text-foreground/70"><Plug className="inline h-3 w-3 -translate-y-px mr-1" />{t("details.mcpServers")} </span>
                    {servers.map((s, i) => (
                      <span key={s.name} title={s.description || undefined}>
                        {i > 0 && ", "}
                        <span className="font-mono">{s.name}</span>
                        <span className="text-muted-foreground/70"> ({s.command ? `stdio: ${s.command}` : s.url})</span>
                      </span>
                    ))}
                  </div>
                ) : null;
              })()}

              {(() => {
                const creds = (
                  Array.isArray(args.declared_creds) ? args.declared_creds : []
                ) as Array<{ vault_path: string; name?: string; description?: string }>;
                return creds.length > 0 ? (
                  <div>
                    <div className="text-[11px] font-medium text-foreground/70 mb-1"><KeyRound className="inline h-3 w-3 -translate-y-px mr-1" />{t("details.credentials")}</div>
                    <table className="text-[11px] w-full border-collapse">
                      <thead>
                        <tr className="text-left text-muted-foreground/70">
                          <th className="font-medium pr-3 pb-0.5">{t("details.name")}</th>
                          <th className="font-medium pr-3 pb-0.5">{t("details.path")}</th>
                          <th className="font-medium pb-0.5">{t("details.description")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {creds.map((c) => (
                          <tr key={c.vault_path} className="text-muted-foreground">
                            <td className="pr-3 py-0.5 font-mono text-foreground/85">{c.name || c.vault_path}</td>
                            <td className="pr-3 py-0.5 font-mono text-muted-foreground/70">{c.name ? c.vault_path : ""}</td>
                            <td className="py-0.5">{c.description ?? ""}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null;
              })()}

              {useSkillStatus && (
                <div>
                  <div className="text-[11px] font-medium text-foreground/70 mb-1"><Zap className="inline h-3 w-3 -translate-y-px mr-1" />{t("details.activation")}</div>
                  <div className="text-[11px] text-muted-foreground whitespace-pre-wrap">
                    {useSkillStatus}
                  </div>
                </div>
              )}

              {useSkillInstructions && (
                <div className="rounded-md border border-border/40 overflow-hidden">
                  <button
                    type="button"
                    onClick={() => setSkillInstructionsOpen(!skillInstructionsOpen)}
                    className="flex w-full items-center gap-1.5 px-2.5 py-1.5 text-xs text-left hover:bg-accent/50 transition-colors"
                  >
                    <ChevronRight
                      className={cn(
                        "h-3 w-3 shrink-0 transition-transform",
                        skillInstructionsOpen && "rotate-90",
                      )}
                    />
                    <span className="font-medium text-foreground/70">{t("details.skillInstructions")}</span>
                  </button>
                  {skillInstructionsOpen && (
                    <div className="border-t border-border/40">
                      <MarkdownContent content={useSkillInstructions} />
                    </div>
                  )}
                </div>
              )}

              {result != null && !useSkillSplit && (
                <div
                  className={cn(
                    "rounded-md border overflow-hidden",
                    isError
                      ? "border-destructive/30 bg-destructive/5"
                      : "border-border/40",
                  )}
                >
                  <MarkdownContent content={useSkillResult} />
                </div>
              )}
            </div>
          ) : isReadTool && readSplit?.hasSplit ? (
            <>
              <div
                className={cn(
                  "rounded-md border bg-muted/25 px-3 py-2",
                  isError ? "border-destructive/30" : "border-border/40",
                )}
              >
                <div className="whitespace-pre-wrap text-muted-foreground leading-relaxed">
                  {readSplit.header}
                </div>
              </div>
              <div
                className={cn(
                  "max-w-none [&_.prose]:max-w-none",
                  isError &&
                    "[&_.prose_.md-code-block-shell]:border-destructive/40 [&_.prose_.md-code-block-shell]:bg-destructive/5",
                )}
              >
                <MarkdownContent content={readBodyMarkdown} />
              </div>
            </>
          ) : isWriteTool ? (
            <>
              <div
                className={cn(
                  "max-w-none [&_.prose]:max-w-none",
                  isError &&
                    "[&_.prose_.md-code-block-shell]:border-destructive/40 [&_.prose_.md-code-block-shell]:bg-destructive/5",
                )}
              >
                <MarkdownContent content={writeContentMarkdown} />
              </div>
              {result != null && result.length > 0 && (
                <div
                  className={cn(
                    "rounded-md border bg-muted/25 px-3 py-2",
                    isError ? "border-destructive/30" : "border-border/40",
                  )}
                >
                  <div className="whitespace-pre-wrap text-muted-foreground leading-relaxed">
                    {result}
                  </div>
                </div>
              )}
            </>
          ) : isStrReplaceTool ? (
            <>
              <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                <div
                  className={cn(
                    "max-w-none [&_.prose]:max-w-none",
                    isError &&
                      "[&_.prose_.md-code-block-shell]:border-destructive/40 [&_.prose_.md-code-block-shell]:bg-destructive/5",
                  )}
                >
                  <div className="mb-1 text-[11px] font-medium text-muted-foreground">
                    {t("details.source")}
                  </div>
                  <MarkdownContent content={strReplaceSourceMarkdown} />
                </div>
                <div
                  className={cn(
                    "max-w-none [&_.prose]:max-w-none",
                    isError &&
                      "[&_.prose_.md-code-block-shell]:border-destructive/40 [&_.prose_.md-code-block-shell]:bg-destructive/5",
                  )}
                >
                  <div className="mb-1 text-[11px] font-medium text-muted-foreground">
                    {t("details.replacement")}
                  </div>
                  <MarkdownContent content={strReplaceReplacementMarkdown} />
                </div>
              </div>
              <div
                className={cn(
                  "max-w-none [&_.prose]:max-w-none",
                  isError &&
                    "[&_.prose_.md-code-block-shell]:border-destructive/40 [&_.prose_.md-code-block-shell]:bg-destructive/5",
                )}
              >
                <div className="mb-1 text-[11px] font-medium text-muted-foreground">
                  {t("details.diff")}
                </div>
                <MarkdownContent content={strReplaceDiffMarkdown} />
              </div>
              {result != null && result.length > 0 && (
                <div
                  className={cn(
                    "rounded-md border bg-muted/25 px-3 py-2",
                    isError ? "border-destructive/30" : "border-border/40",
                  )}
                >
                  <div className="whitespace-pre-wrap text-muted-foreground leading-relaxed">
                    {result}
                  </div>
                </div>
              )}
            </>
          ) : isSendFileTool ? (
            <>
              {files && files.length > 0 ? (
                <div className="space-y-2">
                  {files.map((file) => (
                    <FilePreview
                      key={file.file_id}
                      fileId={file.file_id}
                      name={file.name}
                      path={typeof args.path === "string" ? args.path : undefined}
                      mime={file.mime}
                      size={file.size}
                      server={server}
                      sessionId={sessionId}
                    />
                  ))}
                </div>
              ) : (
                <div className="text-muted-foreground">{result ?? ""}</div>
              )}
            </>
          ) : (
            <>
              <details open>
                <summary className="cursor-pointer text-muted-foreground hover:text-foreground transition-colors font-medium select-none">
                  {t("details.arguments")}
                </summary>
                <pre className="mt-1.5 rounded-md bg-muted p-2.5 font-mono overflow-x-auto border border-border/40">
                  {JSON.stringify(args, null, 2)}
                </pre>
              </details>

              {result != null && (
                <details open>
                  <summary className="cursor-pointer text-muted-foreground hover:text-foreground transition-colors font-medium select-none">
                    {t("details.result")}
                  </summary>
                  <pre
                    className={cn(
                      "mt-1.5 rounded-md p-2.5 font-mono overflow-x-auto max-h-48 overflow-y-auto whitespace-pre-wrap border",
                      isError
                        ? "bg-destructive/10 text-destructive border-destructive/30"
                        : "bg-muted border-border/40",
                    )}
                  >
                    {result}
                  </pre>
                </details>
              )}
            </>
          )}

          {childCalls && childCalls.length > 0 && (
            <div className="space-y-1">
              {childCalls.map((child, i) => (
                <ToolCallBadge
                  key={child.tool + i}
                  {...child}
                  server={child.server ?? server}
                  sessionId={child.sessionId ?? sessionId}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
