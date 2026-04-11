"use client";

import { useState } from "react";
import {
  ChevronRight,
  Loader2,
  ShieldCheck,
  ShieldAlert,
  UserCheck,
  Puzzle,
  Zap,
} from "lucide-react";
import { diffLines } from "diff";
import { MarkdownContent } from "./markdown-content";
import {
  fencedCodeBlock,
  languageFromFilePath,
  splitReadToolResult,
} from "@/lib/sandbox-read";
import { cn } from "@/lib/utils";

interface ToolCallBadgeProps {
  tool: string;
  args: Record<string, unknown>;
  detail: string;
  contexts?: string[];
  approvalSource?: ApprovalSource;
  approvalVerdict?: ApprovalVerdict;
  approvalExplanation?: string;
  result?: string;
  exitCode?: number;
  loading?: boolean;
}

type ApprovalSource = "safe-list" | "sentinel" | "user" | "skill" | "bypass" | "unknown";
type ApprovalVerdict = "allow" | "deny" | "escalate";

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

function formatReadSummary(args: Record<string, unknown>): string {
  const path = stringArg(args, "path") || "(missing path)";
  const offset = Math.max(0, intArg(args, "offset") ?? 0);
  const limit = Math.max(1, intArg(args, "limit") ?? 100);
  if (offset === 0) {
    return `first ${limit} lines of ${path}`;
  }
  const start = offset + 1;
  const end = offset + limit;
  return `lines ${start} to ${end} of ${path}`;
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
): string {
  const fallback = formatReadSummary(args);
  if (!split?.hasSplit) return fallback;
  const offset = Math.max(0, intArg(args, "offset") ?? 0);
  const limit = Math.max(1, intArg(args, "limit") ?? 100);
  const bodyLines = countOutputLines(split.body);

  if (offset === 0 && bodyLines < limit) return path;
  if (offset === 0) return `first ${bodyLines || limit} lines of ${path}`;

  if (bodyLines > 0) {
    const start = offset + 1;
    const end = offset + bodyLines;
    return `lines ${start} to ${end} of ${path}`;
  }
  return fallback;
}

function formatWriteSummary(args: Record<string, unknown>): string {
  const path = stringArg(args, "path") || "(missing path)";
  const contentLines = lineCount(stringArg(args, "content"));
  return `${contentLines} lines to ${path}`;
}

function formatStrReplaceSummary(args: Record<string, unknown>): string {
  const path = stringArg(args, "path") || "(missing path)";
  const srcLines = lineCount(stringArg(args, "old_string"));
  const dstLines = lineCount(stringArg(args, "new_string"));
  const replaceAll = boolArg(args, "replace_all");
  const lineSummary =
    srcLines === dstLines
      ? `${srcLines} lines`
      : `${srcLines} lines with ${dstLines} lines`;
  const suffix = replaceAll ? " (all matches)" : "";
  return `${lineSummary} in ${path}${suffix}`;
}

function formatCredentialAccessSummary(args: Record<string, unknown>): string {
  const vaultPath = stringArg(args, "vault_path");
  if (!vaultPath || vaultPath === "<list>") return "";
  return vaultPath;
}

function formatProxyDomainSummary(args: Record<string, unknown>): string {
  return stringArg(args, "domain");
}

function formatArgsSummary(
  tool: string,
  args: Record<string, unknown>,
): string {
  if (tool === "write") return formatWriteSummary(args);
  if (tool === "str_replace") return formatStrReplaceSummary(args);
  if (tool === "credential_access") return formatCredentialAccessSummary(args);
  if (tool === "proxy_domain") return formatProxyDomainSummary(args);

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
  return "(missing command)";
}

function buildShellTranscript(command: string, output?: string): string {
  const body = ["❯ " + command];
  const normalizedOutput = output?.replace(/\n+$/, "") ?? "";
  if (normalizedOutput.length > 0) body.push(normalizedOutput);
  const payload = body.join("\n");
  const fence = payload.includes("~~~") ? "~~~~" : "~~~";
  return `${fence}shell\n${payload}\n${fence}`;
}

function getUseSkillName(args: Record<string, unknown>): string {
  const raw = args.skill_name;
  if (typeof raw === "string" && raw.trim().length > 0) return raw;
  return "(missing skill_name)";
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

function ApprovalBadge({
  source,
  verdict,
}: {
  source: ApprovalSource;
  verdict: ApprovalVerdict;
}) {
  if (source === "safe-list") {
    return (
      <span className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-medium bg-blue-500/10 text-blue-600 dark:text-blue-400">
        <ShieldCheck className="h-2.5 w-2.5" />
        auto
      </span>
    );
  }

  if (source === "sentinel") {
    const colorClass =
      verdict === "allow"
        ? "bg-green-500/10 text-green-600 dark:text-green-400"
        : verdict === "deny"
          ? "bg-red-500/10 text-red-600 dark:text-red-400"
          : "bg-yellow-500/10 text-yellow-600 dark:text-yellow-400";
    return (
      <span
        className={cn(
          "inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-medium",
          colorClass,
        )}
      >
        <ShieldAlert className="h-2.5 w-2.5" />
        sentinel
      </span>
    );
  }

  if (source === "user") {
    return (
      <span className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-medium bg-purple-500/10 text-purple-600 dark:text-purple-400">
        <UserCheck className="h-2.5 w-2.5" />
        user
      </span>
    );
  }

  if (source === "skill") {
    return (
      <span className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-medium bg-teal-500/10 text-teal-600 dark:text-teal-400">
        <Puzzle className="h-2.5 w-2.5" />
        skill
      </span>
    );
  }

  if (source === "bypass") {
    return (
      <span className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-medium bg-gray-500/10 text-gray-500 dark:text-gray-400">
        <Zap className="h-2.5 w-2.5" />
        bypass
      </span>
    );
  }

  if (verdict === "deny") {
    return (
      <span className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-medium bg-red-500/10 text-red-600 dark:text-red-400">
        <ShieldAlert className="h-2.5 w-2.5" />
        denied
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
  result,
  exitCode,
  loading,
}: ToolCallBadgeProps) {
  const [open, setOpen] = useState(false);
  void _detail;
  const source = approvalSource;
  const verdict = approvalVerdict ?? "allow";
  const explanation = source === "sentinel" ? (approvalExplanation ?? "") : "";
  const isError = exitCode != null && exitCode !== 0;
  const isExecTool = tool === "exec";
  const isUseSkillTool = tool === "use_skill";
  const isReadTool = tool === "read";
  const isWriteTool = tool === "write";
  const isStrReplaceTool = tool === "str_replace";
  const isCredentialAccessTool = tool === "credential_access";
  const isProxyDomainTool = tool === "proxy_domain";
  const isAuxiliaryTool = isCredentialAccessTool || isProxyDomainTool;
  const readPath = isReadTool && typeof args.path === "string" ? args.path : "";
  const readSplit =
    isReadTool && result != null ? splitReadToolResult(result) : null;
  const readBodyMarkdown =
    readSplit?.hasSplit === true
      ? fencedCodeBlock(languageFromFilePath(readPath), readSplit.body)
      : "";
  const execCommand = isExecTool ? getExecCommand(args) : "";
  const execTitle = isExecTool ? stringArg(args, "title") : "";
  const execTranscript = isExecTool
    ? buildShellTranscript(execCommand, result)
    : "";
  const useSkillName = isUseSkillTool ? getUseSkillName(args) : "";
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
  const isSuccessful = isCompleted && !isError;
  const toolLabel = isSuccessful
    ? isWriteTool
      ? "wrote"
      : isStrReplaceTool
        ? "replaced"
        : isUseSkillTool
          ? "activated skill"
          : isExecTool
            ? "executed"
            : isCredentialAccessTool
              ? isCredentialList
                ? "listed credentials"
                : verdict === "deny"
                  ? "credential denied"
                  : "accessed credential"
              : isProxyDomainTool
                ? verdict === "deny"
                  ? "domain denied"
                  : "accessed domain"
                : tool
    : isUseSkillTool
      ? "activate skill"
      : isExecTool
        ? "execute"
        : isCredentialAccessTool
          ? isCredentialList
            ? "list credentials"
            : "access credential"
          : isProxyDomainTool
            ? "access domain"
            : isStrReplaceTool
              ? "replace"
              : tool;
  const argsSummary =
    isExecTool && execTitle
      ? execTitle
      : isReadTool
        ? formatReadSummaryFromSplit(args, readPath || "(missing path)", readSplit)
        : formatArgsSummary(tool, args);
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

  return (
    <div className="my-1 w-full min-w-0">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={cn(
          "flex w-full min-w-0 items-center gap-1.5 rounded-md px-2 py-1 text-xs text-left",
          "bg-muted/60 text-muted-foreground",
          "hover:bg-accent transition-colors",
          isAuxiliaryTool && "ml-4 w-[calc(100%-1rem)] bg-muted/40",
        )}
      >
        <ChevronRight
          className={cn(
            "h-3 w-3 shrink-0 transition-transform",
            open && "rotate-90",
          )}
        />
        <span className="shrink-0 font-mono font-medium text-foreground/80">
          {toolLabel}
        </span>
        {argsSummary ? (
          <span
            className="min-w-0 flex-1 truncate font-mono text-[11px] text-foreground/65 dark:text-foreground/70"
            title={argsSummary}
          >
            {argsSummary}
          </span>
        ) : null}
        <span className="ml-auto inline-flex shrink-0 items-center gap-1">
          {source && <ApprovalBadge source={source} verdict={verdict} />}
          {loading && (
            <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
          )}
        </span>
      </button>

      {open && (
        <div className="ml-5 mt-1.5 rounded-lg border border-border/60 bg-muted/30 p-3 space-y-2 text-xs">
          {explanation && (
            <div className="text-muted-foreground leading-relaxed">
              <span className="font-medium text-foreground/70">Sentinel: </span>
              {explanation}
            </div>
          )}

          {contexts && contexts.length > 0 && (
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="text-[11px] font-medium text-muted-foreground">Contexts:</span>
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
            <>
              <div className="text-muted-foreground">
                Agent wants to activate the{" "}
                <span className="font-mono text-foreground/85">
                  {useSkillName}
                </span>{" "}
                skill.
              </div>

              {result != null && (
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
            </>
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
                    Source
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
                    Replacement
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
                  Diff
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
          ) : (
            <>
              <details open>
                <summary className="cursor-pointer text-muted-foreground hover:text-foreground transition-colors font-medium select-none">
                  Arguments
                </summary>
                <pre className="mt-1.5 rounded-md bg-muted p-2.5 font-mono overflow-x-auto border border-border/40">
                  {JSON.stringify(args, null, 2)}
                </pre>
              </details>

              {result != null && (
                <details open>
                  <summary className="cursor-pointer text-muted-foreground hover:text-foreground transition-colors font-medium select-none">
                    Result
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
        </div>
      )}
    </div>
  );
}
