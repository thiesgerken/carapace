"use client";

import { useTranslations } from "next-intl";
import { useCallback, useState } from "react";
import {
  Archive,
  Ban,
  ChevronRight,
  ExternalLink,
  FileText,
  FilePen,
  GitBranch,
  Globe,
  History,
  Hourglass,
  KeyRound,
  MessageSquareText,
  Puzzle,
  Replace,
  Send,
  Shield,
  ShieldAlert,
  ShieldCheck,
  ShieldX,
  SquareTerminal,
  UserCheck,
  UserX,
  Zap,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { diffLines } from "diff";
import { MarkdownContent } from "./markdown-content";
import { CodeBlockShell } from "./markdown-code-pre";
import { FilePreview } from "./file-preview";
import { ArtifactPreview } from "./artifact-preview";
import { BrailleSpinner } from "./braille-spinner";
import { ActivityCounter, Elapsed } from "./waiting-indicator";
import {
  fencedCodeBlock,
  languageFromFilePath,
  splitReadToolResult,
  verbatimCodeBlock,
} from "@/lib/sandbox-read";
import { splitHeredocs, splitLastLines, type CommandFragment } from "@/lib/shell-heredoc";
import type { ApprovalSource, ApprovalVerdict, CompactionAnnotation, LlmActivity, RunningSpan, SentFile } from "@/lib/types";
import { stepTopic, toolCallStatus, type RunningStep } from "@/lib/tool-call-status";
import { cn } from "@/lib/utils";
import { getArtifact, knowledgeArtifactUrl, knowledgeRawUrl } from "@/lib/api";
import { ArtifactIcon, artifactViewerHref, type ArtifactReference } from "@/lib/artifacts";
import { useDebounced } from "@/hooks/use-debounced";
import { useKeyedFetch } from "@/hooks/use-keyed-fetch";
import { parseStreamingArgs } from "@/lib/live-tool-calls";

interface ToolCallBadgeProps {
  tool: string;
  args: Record<string, unknown>;
  detail: string;
  approvalSource?: ApprovalSource;
  approvalVerdict?: ApprovalVerdict;
  approvalExplanation?: string;
  /** What the sentinel told the agent about the operation it allowed. */
  approvalComment?: string;
  decisionMessage?: string;
  result?: string;
  files?: SentFile[];
  exitCode?: number;
  loading?: boolean;
  compaction?: CompactionAnnotation;
  childCalls?: ToolCallBadgeProps[];
  server?: string;
  sessionId?: string;
  /** The raw JSON args while the model streams the call; `args` holds what parses of them so far. */
  argsText?: string;
  /** The model is still writing the args: the card shows them growing. */
  argsStreaming?: boolean;
  /** The streamed call never ran. */
  notRun?: boolean;
  /** The call's steps still running; while it loads, the card names the innermost one. */
  runningSpans?: RunningSpan[];
  /** The agent request writing this call right now: the card shows its counter. */
  streamingActivity?: LlmActivity | null;
  /** Set on a successful `show_artifact` call: the card then shows the artifact live. */
  artifactReference?: ArtifactReference;
}

const TOOL_ICONS: Record<string, LucideIcon> = {
  exec: SquareTerminal,
  read: FileText,
  write: FilePen,
  str_replace: Replace,
  read_skill: Puzzle,
  credential_access: KeyRound,
  proxy_domain: Globe,
  git_push: GitBranch,
  send_file: Send,
  show_artifact: ArtifactIcon,
  read_tool_output: History,
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
  read_skill: new Set(["skill_name"]),
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
  if (tool === "read_skill") return stringArg(args, "skill_name");
  if (tool === "write") return formatWriteSummary(args, t);
  if (tool === "str_replace") return formatStrReplaceSummary(args, t);
  if (tool === "credential_access") return formatCredentialAccessSummary(args);
  if (tool === "proxy_domain") return formatProxyDomainSummary(args);
  if (tool === "git_push") return stringArg(args, "ref");

  const omit = OMIT_ARG_LABEL[tool];
  const parts: string[] = [];
  for (const [k, v] of Object.entries(args)) {
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

/** A command's first line, marked as cut when there is more: the row has room for one, the details show it all. */
function firstLine(command: string): string {
  const text = command.trim();
  const end = text.indexOf("\n");
  return end === -1 ? text : `${text.slice(0, end).trimEnd()} …`;
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

/** *command* as shell and heredoc fragments, with *prompt* in front of its first line. */
function promptedFragments(command: string, prompt: string): CommandFragment[] {
  const [first, ...rest] = splitHeredocs(command.replace(/\n+$/, ""));
  return [{ ...first, code: prompt + first.code }, ...rest];
}

/** Verbatim fences: blank lines ending a fragment are lines of the command, and its line numbers run on across fragments. */
function fragmentsMarkdown(fragments: CommandFragment[]): string {
  return fragments.map(({ language, code }) => verbatimCodeBlock(language, code)).join("\n\n");
}

function formatSkillResult(result: string): string {
  const normalized = result.replace(/\n+$/, "");
  // Render YAML front matter as fenced YAML for readable syntax highlighting.
  return normalized.replace(
    /(^|\n)---\n([\s\S]*?)\n---(?=\n|$)/,
    (_m, prefix: string, yamlBody: string) =>
      `${prefix}\`\`\`yaml\n${yamlBody.trim()}\n\`\`\``,
  );
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
  isReadSkillTool: boolean;
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
    isReadSkillTool,
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
    if (isReadSkillTool) return t("labels.readSkill");
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
  if (isReadSkillTool) return t("labels.readSkillAction");
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

/** Which tooltip title explains this decision; the explanation, if any, follows it. */
function approvalTitleKey(source: ApprovalSource, verdict?: ApprovalVerdict): string | null {
  switch (source) {
    case "sentinel":
      return verdict == null ? "sentinelPending" : `sentinel_${verdict}`;
    case "user":
      return verdict === "deny" ? "userDeny" : "userAllow";
    case "skill":
    case "autonomy":
    case "bypass":
    case "policy":
      return source;
    default:
      return verdict === "deny" ? "denied" : null;
  }
}

function ApprovalBadge({
  source,
  verdict,
  explanation,
}: {
  source: ApprovalSource;
  verdict?: ApprovalVerdict;
  explanation?: string;
}) {
  const t = useTranslations("toolCallBadge.approvalBadge");
  const titleKey = approvalTitleKey(source, verdict);
  if (titleKey == null) return null;
  const title = explanation ? `${t(`titles.${titleKey}`)}: ${explanation}` : t(`titles.${titleKey}`);

  if (source === "sentinel") {
    if (verdict == null) {
      return (
        <span
          className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-medium bg-muted text-muted-foreground"
          title={title}
        >
          <BrailleSpinner className="text-xs" />
          {t("review")}
        </span>
      );
    }
    const { Icon, colorClass } = SENTINEL_VERDICT_ICONS[verdict];
    return (
      <span className={cn("inline-flex shrink-0 items-center", colorClass)} title={title}>
        <Icon className="h-3 w-3" />
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
            ? "text-destructive"
            : "text-success",
        )}
        title={title}
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
      <span
        className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-medium bg-success/10 text-success"
        title={title}
      >
        <Puzzle className="h-2.5 w-2.5" />
        {t("skill")}
      </span>
    );
  }

  if (source === "autonomy") {
    return (
      <span
        className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-medium bg-destructive/10 text-destructive"
        title={title}
      >
        <Hourglass className="h-2.5 w-2.5" />
        {t("autonomy")}
      </span>
    );
  }

  if (source === "bypass") {
    return (
      <span
        className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-medium bg-warning/10 text-warning"
        title={title}
      >
        <Zap className="h-2.5 w-2.5" />
        {t("bypass")}
      </span>
    );
  }

  if (source === "policy") {
    return (
      <span
        className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-medium bg-destructive/10 text-destructive"
        title={title}
      >
        <Ban className="h-2.5 w-2.5" />
        {t("policy")}
      </span>
    );
  }

  return (
    <span
      className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-medium bg-destructive/10 text-destructive"
      title={title}
    >
      <ShieldX className="h-2.5 w-2.5" />
      {t("denied")}
    </span>
  );
}

const SENTINEL_VERDICT_ICONS: Record<ApprovalVerdict, { Icon: LucideIcon; colorClass: string }> = {
  allow: { Icon: ShieldCheck, colorClass: "text-success" },
  deny: { Icon: ShieldX, colorClass: "text-destructive" },
  escalate: { Icon: ShieldAlert, colorClass: "text-warning" },
};

/** What the card says while *step* runs; `read_skill` waits for a build and a profile sync. */
function stepLabel(step: RunningStep, t: TranslateFn): string {
  const topic = stepTopic(step);
  return topic === "domain" ? t("status.domain", { domain: step.name }) : t(`status.${topic}`);
}

/** *step* in the words of its card, for places that name it outside the card. */
export function StepLabel({ step }: { step: RunningStep }) {
  const t = useTranslations("toolCallBadge");
  return stepLabel(step, t);
}

export function ToolCallBadge({
  tool,
  args,
  detail: _detail,
  approvalSource,
  approvalVerdict,
  approvalExplanation,
  approvalComment,
  decisionMessage,
  result,
  files,
  exitCode,
  loading,
  compaction,
  childCalls,
  server,
  sessionId,
  argsText,
  argsStreaming,
  notRun,
  runningSpans,
  streamingActivity,
  artifactReference,
}: ToolCallBadgeProps) {
  const t = useTranslations("toolCallBadge");
  const step = loading ? toolCallStatus(runningSpans) : null;
  const tc = useTranslations("compaction");
  const ta = useTranslations("artifacts");
  const isSendFileTool = tool === "send_file";
  const artifactSlug = artifactReference?.slug ?? null;
  const [open, setOpen] = useState(isSendFileTool);
  // ponytail: one metadata fetch per reference; dedupe per slug if long artifact sessions get slow.
  const loadArtifact = useCallback(() => getArtifact(server!, artifactSlug!), [server, artifactSlug]);
  const liveArtifact = useKeyedFetch(
    artifactReference && server !== undefined ? `${server}\n${artifactReference.slug}\n${artifactReference.revision}` : null,
    loadArtifact,
  );
  const liveArtifactValue = liveArtifact && "value" in liveArtifact ? liveArtifact.value : undefined;
  // A deleted or renamed artifact has nothing to expand; the row itself says so.
  const artifactMissing = liveArtifactValue === null;
  const expanded = open && !artifactMissing;
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
  const policyExplanation = source === "policy" ? explanation : "";
  const showUserDecision =
    source === "user" && (verdict === "deny" || finalDecisionMessage.length > 0);
  const isError = exitCode != null && exitCode !== 0;
  const isExecTool = tool === "exec";
  const isReadSkillTool = tool === "read_skill";
  const isReadTool = tool === "read";
  const isWriteTool = tool === "write";
  const isStrReplaceTool = tool === "str_replace";
  const isCredentialAccessTool = tool === "credential_access";
  const isProxyDomainTool = tool === "proxy_domain";
  const isGitPushTool = tool === "git_push";
  const isAuxiliaryTool = isCredentialAccessTool || isProxyDomainTool || isGitPushTool;
  const readPath = isReadTool && typeof args.path === "string" ? args.path : "";
  const readSplit =
    isReadTool && result != null ? splitReadToolResult(result) : null;
  const readBodyMarkdown =
    readSplit?.hasSplit === true
      ? fencedCodeBlock(languageFromFilePath(readPath), readSplit.body)
      : "";
  const execCommand = isExecTool ? getExecCommand(args) : "";
  // While the model writes the call, the title shows once it is complete; until then, the command's first line.
  const execTitle = isExecTool
    ? normalizeOptionalLabel(stringArg(argsStreaming ? parseStreamingArgs(argsText ?? "", false) ?? {} : args, "title"))
    : "";
  const execCommandMarkdown = isExecTool
    ? fragmentsMarkdown(promptedFragments(execCommand || t("fallbacks.missingCommand"), "❯ "))
    : "";
  const execOutput = isExecTool ? result?.replace(/\n+$/, "") ?? "" : "";
  const skillResult = isReadSkillTool && result != null ? formatSkillResult(result) : "";
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
  const toolLabel = artifactReference
    ? [
        t(artifactReference.update ? "labels.artifactUpdated" : "labels.artifact", { title: liveArtifactValue?.title ?? artifactReference.slug }),
        ...(artifactMissing ? [t("labels.noLongerExists")] : []),
      ].join(" · ")
    : resolveToolLabel(
    {
      tool,
      isCompleted,
      isReadTool,
      isWriteTool,
      isStrReplaceTool,
      isReadSkillTool,
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
      ? execTitle || firstLine(execCommand) || (argsStreaming ? "" : t("fallbacks.missingCommand"))
      : isReadTool
        ? formatReadSummaryFromSplit(
            args,
            readPath || t("fallbacks.missingPath"),
            readSplit,
            t,
          )
        : formatArgsSummary(tool, args, t);
  const shouldClampSummary = argsSummary.length > MULTILINE_SUMMARY_THRESHOLD;
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
        const credentialCalls = childCalls?.filter((c) => c.tool === "credential_access") ?? [];
        const credCount = credentialCalls.length;
        const credTooltip = credentialCalls
          .map((c) => (c.args.name as string | undefined) || (c.args.vault_path as string | undefined) || t("fallbacks.credential"))
          .join("\n");
        const domainCalls = childCalls?.filter((c) => c.tool === "proxy_domain") ?? [];
        const domainCount = domainCalls.length;
        const domainTooltip = domainCalls.map((c) => (c.args.domain as string) ?? "").join("\n");

        return (
          <>
            {credCount > 0 && (
              <span
                className="inline-flex items-center gap-0.5 rounded bg-info/10 px-1.5 py-0.5 text-[10px] text-info"
                title={credTooltip}
              >
                <KeyRound className="h-2.5 w-2.5" />{credCount}
              </span>
            )}
            {domainCount > 0 && (
              <span
                className="inline-flex items-center gap-0.5 rounded bg-info/10 px-1.5 py-0.5 text-[10px] text-info"
                title={domainTooltip}
              >
                <Globe className="h-2.5 w-2.5" />{domainCount}
              </span>
            )}
          </>
        );
      })()}
      {source && <ApprovalBadge source={source} verdict={verdict} explanation={finalDecisionMessage || sentinelExplanation || policyExplanation || undefined} />}
      {approvalComment && (
        <span className="inline-flex shrink-0 items-center text-success" title={approvalComment}>
          <MessageSquareText className="h-3 w-3" />
        </span>
      )}
      {/* A folded tool row is outside the model's context entirely; the fold rail tells that story. */}
      {compaction?.orig_tokens != null && compaction.folded_into == null && (
        <span
          className="inline-flex items-center rounded bg-info/10 p-0.5 text-info"
          title={tc("toolTitle", {
            orig: compaction.orig_tokens ?? 0,
            summary: compaction.summary_tokens ?? 0,
          })}
        >
          <Archive className="h-2.5 w-2.5" />
        </span>
      )}
      {notRun && (
        <span className="inline-flex items-center gap-0.5 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground" title={t("notRunTitle")}>
          <Ban className="h-2.5 w-2.5" />
          {t("notRun")}
        </span>
      )}
      {streamingActivity && <ActivityCounter activity={streamingActivity} />}
      {loading && (
        <BrailleSpinner className="text-sm text-muted-foreground" />
      )}
    </span>
  );

  return (
    <div className="my-1 w-full min-w-0">
      <div className={cn(
        artifactSlug !== null && "flex items-stretch rounded-md text-muted-foreground hover:bg-accent transition-colors",
        artifactSlug !== null && expanded && "bg-accent",
      )}>
        <button
          type="button"
          onClick={() => setOpen(!open)}
          disabled={artifactMissing}
          aria-expanded={artifactMissing ? undefined : expanded}
          className={cn(
            "flex min-w-0 gap-1.5 rounded-md px-2 py-1 text-xs text-left",
            artifactSlug === null ? "w-full" : "pr-0",
            shouldClampSummary ? "items-start" : "items-center",
            "text-muted-foreground hover:bg-accent transition-colors disabled:hover:bg-transparent",
            expanded && "bg-accent",
          )}
        >
          <ChevronRight
            className={cn(
              "h-3 w-3 shrink-0 transition-transform",
              expanded && "rotate-90",
              artifactMissing && "invisible",
            )}
          />
          {(() => {
            const ToolIcon = artifactSlug !== null ? ArtifactIcon : TOOL_ICONS[tool];
            return ToolIcon ? (
              <ToolIcon className="h-3 w-3 shrink-0 text-foreground/65 dark:text-foreground/70" />
            ) : null;
          })()}
          <span className={cn("font-medium", artifactMissing ? "text-muted-foreground" : "text-foreground/85 dark:text-foreground/90", artifactSlug !== null ? "min-w-0 truncate" : "shrink-0")} title={artifactSlug !== null ? toolLabel : undefined}>
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
            {!artifactMissing && <a
              href={artifactViewerHref(artifactSlug)}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={ta("openLiveInNewTab")}
              title={ta("openLiveInNewTab")}
              className="inline-flex shrink-0 items-center rounded-md p-1.5 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <ExternalLink className="h-3 w-3" />
            </a>}
            <button
              type="button"
              tabIndex={-1}
              aria-hidden="true"
              onClick={() => setOpen(!open)}
              disabled={artifactMissing}
              className="flex flex-1 items-center justify-end rounded-md py-1 pl-1.5 pr-2"
            >
              {indicators}
            </button>
          </>
        )}
      </div>

      {/* An open card says it in its details, with how long the step has run. */}
      {step && !expanded && (
        <div role="status" className="ml-5 truncate text-[11px] text-muted-foreground">
          {stepLabel(step, t)}
        </div>
      )}

      {argsStreaming && !open && <StreamingArgs fragments={streamingPreview(tool, args, argsText ?? "")} />}

      {expanded && (
        <div className="tool-row-details ml-5 mt-1.5 rounded-lg border border-border/60 bg-inset p-3 space-y-2 text-xs">
          {step && (
            <div role="status" className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <BrailleSpinner className="text-xs" />
              <span className="min-w-0 truncate">{stepLabel(step, t)}</span>
              <span aria-hidden>·</span>
              <Elapsed since={step.startedAt} />
            </div>
          )}
          {compaction?.model_text && (
            <details className="rounded-md border border-info/30 bg-info/5">
              <summary className="flex cursor-pointer list-none items-center gap-1 px-2 py-1 text-[11px] text-muted-foreground hover:bg-accent/50">
                <Archive className="h-3 w-3 text-info" />
                <span className="font-medium">{tc("modelSees")}</span>
                <span className="opacity-70">
                  · {tc("tokenDelta", { from: compaction.orig_tokens ?? 0, to: compaction.summary_tokens ?? 0 })}
                </span>
              </summary>
              <div className="whitespace-pre-wrap break-words border-t border-info/20 px-2 py-1.5 font-mono text-[11px] text-muted-foreground">
                {compaction.model_text}
              </div>
            </details>
          )}
          {isSentinelReviewPending && (
            <div className="text-[11px] text-muted-foreground leading-relaxed">
                <span className="font-medium text-foreground/70">
                  <BrailleSpinner className="mr-1 text-xs" />
                  {t("details.sentinelLabel")}
                </span>{" "}
                {t("details.sentinelReviewing")}
            </div>
          )}

          {sentinelExplanation && (
            <div className="text-[11px] text-muted-foreground leading-relaxed">
                <span className="font-medium text-foreground/70">
                  <Shield className="inline h-3 w-3 -translate-y-px mr-1" />
                  {t("details.sentinelLabel")}
                </span>{" "}
              {sentinelExplanation}
            </div>
          )}

          {policyExplanation && (
            <div className="text-[11px] text-muted-foreground leading-relaxed">
              <span className="font-medium text-foreground/70">
                <Ban className="inline h-3 w-3 -translate-y-px mr-1" />
                {t("details.proxyLabel")}
              </span>{" "}
              {policyExplanation}
            </div>
          )}

          {approvalComment && (
            <div className="text-[11px] text-muted-foreground leading-relaxed">
              <span className="font-medium text-success">
                <MessageSquareText className="inline h-3 w-3 -translate-y-px mr-1" />
                {t("details.commentForAgent")}
              </span>{" "}
              {approvalComment}
            </div>
          )}

          {showUserDecision && (
            <div className="text-[11px] text-muted-foreground leading-relaxed">
              <span className="font-medium text-foreground/70">{verdict === "deny" ? <UserX className="inline h-3 w-3 -translate-y-px mr-1" /> : <UserCheck className="inline h-3 w-3 -translate-y-px mr-1" />}{t("details.userLabel")} </span>
              {finalDecisionMessage || t("details.deniedByUser")}
            </div>
          )}

          {isExecTool ? (
            <>
              {execTitle && (
                <div className="font-medium text-foreground/80">
                  {execTitle}
                </div>
              )}
              {/* Blocks named by role: the command mixes languages, and its single copy button copies it runnable. */}
              <div className="exec-terminal-block prose">
                <CodeBlockShell label={t("details.command")} copyText={() => execCommand}>
                  <div className="code-fragments exec-block">
                    <MarkdownContent content={execCommandMarkdown} />
                  </div>
                </CodeBlockShell>
                {execOutput && (
                  <CodeBlockShell label={t("details.output")} copyText={() => execOutput}>
                    <div className="code-fragments exec-block">
                      <MarkdownContent content={fencedCodeBlock("text", execOutput)} />
                    </div>
                  </CodeBlockShell>
                )}
              </div>
            </>
          ) : isReadSkillTool ? (
            skillResult && (
              <div className={cn("rounded-md border overflow-hidden", isError ? "border-destructive/30 bg-destructive/5" : "border-border/40")}>
                <MarkdownContent content={skillResult} />
              </div>
            )
          ) : isReadTool && readSplit?.hasSplit ? (
            <>
              <div
                className={cn(
                  "rounded-md border bg-background px-3 py-2",
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
                    "rounded-md border bg-background px-3 py-2",
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
                    "rounded-md border bg-background px-3 py-2",
                    isError ? "border-destructive/30" : "border-border/40",
                  )}
                >
                  <div className="whitespace-pre-wrap text-muted-foreground leading-relaxed">
                    {result}
                  </div>
                </div>
              )}
            </>
          ) : artifactReference && server !== undefined ? (
            liveArtifact === null ? (
              <div className="text-muted-foreground">{ta("loadingArtifact")}</div>
            ) : "error" in liveArtifact ? (
              <p role="alert" className="text-destructive">{ta("loadError")}</p>
            ) : liveArtifact.value === null ? null : (
              <ArtifactPreview
                // A new reference to the slug bumps the revision and remounts the iframe on its current state.
                key={artifactReference.revision}
                src={knowledgeArtifactUrl(server, artifactReference.slug)}
                sourceUrl={knowledgeRawUrl(server, `artifacts/${artifactReference.slug}/index.html`)}
                title={liveArtifact.value.title}
                artifact={{ server, ...liveArtifact.value }}
              />
            )
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

/** Shiki highlights the whole text each time, so a streaming preview re-highlights at most this often. */
const STREAMING_HIGHLIGHT_INTERVAL_MS = 300;

// ponytail: a streaming preview highlights only its last lines, the ones its box shows; the rest stays plain,
// since highlighting a few thousand lines on every update freezes the page. Ceiling: a window that starts
// inside a multi-line string or comment mis-highlights its first lines until they move up out of it.
const STREAMING_HIGHLIGHT_LINES = 200;

/**
 * What a streaming call's args will mainly show once it is final: the command, or the file text. A
 * fragment stays plain `text` until its language is known: `write`'s complete path, or an `exec`
 * heredoc's interpreter or target file.
 */
function streamingPreview(tool: string, args: Record<string, unknown>, argsText: string): CommandFragment[] {
  switch (tool) {
    case "exec": {
      const command = getExecCommand(args);
      if (!command) return [];
      const fragments = promptedFragments(command, "$ ");
      return fragments.length > 1 ? fragments : [{ language: "text", code: fragments[0].code }];
    }
    case "write": {
      const path = stringArg(parseStreamingArgs(argsText, false) ?? {}, "path");
      return [{ language: languageFromFilePath(path), code: stringArg(args, "content") }];
    }
    case "str_replace":
      return [{ language: "text", code: stringArg(args, "new_string") }];
    default:
      return [{ language: "text", code: argsText }];
  }
}

/**
 * The args as the model writes them, in a compact box that keeps the newest lines in view. Plain text is
 * cheap to re-render on every delta; highlighted fragments only update every few hundred milliseconds.
 */
function StreamingArgs({ fragments }: { fragments: CommandFragment[] }) {
  if (fragments.every(({ code }) => !code)) return null;
  const plain = fragments.every(({ language }) => language === "text");
  return (
    // column-reverse anchors the scroll at the bottom, also when a highlight lands after this render.
    <div className="ml-5 mt-1 flex max-h-48 flex-col-reverse overflow-auto rounded-lg border border-border/60 bg-inset p-2 font-mono text-[11px] leading-4 text-foreground/75">
      {plain ? <PlainFragments fragments={fragments} /> : <HighlightedFragments fragments={fragments} />}
    </div>
  );
}

function PlainFragments({ fragments }: { fragments: CommandFragment[] }) {
  return <pre className="whitespace-pre-wrap break-words">{fragments.map(({ code }) => code).join("\n")}</pre>;
}

/**
 * The last lines highlighted below the plain rest. Both come from the same throttled snapshot, so no line
 * shows twice at the boundary. `MarkdownContent` shows its unhighlighted fallback only until the first
 * highlight; after that it keeps the last highlighted render on screen until the next one resolves.
 */
function HighlightedFragments({ fragments }: { fragments: CommandFragment[] }) {
  const settled = useDebounced(fragments, STREAMING_HIGHLIGHT_INTERVAL_MS, STREAMING_HIGHLIGHT_INTERVAL_MS);
  const { head, tail } = splitLastLines(settled, STREAMING_HIGHLIGHT_LINES);
  return (
    <div>
      {head.length > 0 && <PlainFragments fragments={head} />}
      <div className="code-fragments streaming-code">
        <MarkdownContent content={fragmentsMarkdown(tail)} />
      </div>
    </div>
  );
}
