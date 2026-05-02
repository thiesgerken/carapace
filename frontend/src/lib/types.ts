// Session

export type SandboxRuntimeKind = "docker" | "kubernetes";
export type SandboxStatus =
  | "running"
  | "scaled_down"
  | "stopped"
  | "missing"
  | "pending"
  | "error";

export interface SessionSandboxSnapshot {
  exists: boolean;
  runtime?: SandboxRuntimeKind | null;
  status: SandboxStatus;
  resource_id?: string | null;
  resource_kind?: string | null;
  storage_present: boolean;
  provisioned_bytes?: number | null;
  last_measured_used_bytes?: number | null;
  last_measured_at?: string | null;
  updated_at?: string | null;
  last_error?: string | null;
}

export interface SessionAttributes {
  private: boolean;
  archived: boolean;
  pinned: boolean;
  favorite: boolean;
}

export interface SessionAttributesPatch {
  private?: boolean;
  archived?: boolean;
  pinned?: boolean;
  favorite?: boolean;
}

export interface SessionInfo {
  session_id: string;
  channel_type: string;
  channel_ref: string | null;
  created_at: string;
  last_active: string;
  title?: string;
  attributes: SessionAttributes;
  knowledge_last_committed_at?: string | null;
  knowledge_last_archive_path?: string | null;
  knowledge_last_commit_trigger?: string | null;
  activated_rules: string[];
  disabled_rules: string[];
  message_count: number;
  sandbox?: SessionSandboxSnapshot | null;
}

export interface SessionArchiveCommitResponse {
  session: SessionInfo;
  committed: boolean;
  archive_path?: string | null;
  committed_at?: string | null;
  trigger: string;
  reason?: string | null;
}

export interface HistoryMessage {
  role: string;
  content: string;
  event_index?: number;
  reasoning_duration_ms?: number;
  reasoning_tokens?: number;
  tool?: string;
  args?: Record<string, unknown>;
  detail?: string;
  contexts?: string[];
  approval_source?:
    | "safe-list"
    | "sentinel"
    | "user"
    | "skill"
    | "bypass"
    | "unknown";
  approval_verdict?: "allow" | "deny" | "escalate";
  approval_explanation?: string;
  result?: string;
  exit_code?: number;
  command?: string;
  data?: unknown;
  request_id?: string;
  domain?: string;
  decision?: string;
  tool_call_id?: string;
  decision_source?:
    | "safe-list"
    | "sentinel"
    | "user"
    | "skill"
    | "bypass"
    | "unknown";
  message?: string;
  explanation?: string;
  risk_level?: string;
  ref?: string;
  changed_files?: string[];
  vault_paths?: string[];
  names?: string[];
  descriptions?: string[];
  skill_name?: string;
  tool_id?: string;
  parent_tool_id?: string;
}

// WebSocket protocol — Server → Client

export interface TokenChunk {
  type: "token";
  content: string;
}

export interface ThinkingChunk {
  type: "thinking";
  content: string;
}

export type LlmActivityPhase = "processing_prompt" | "thinking" | "generating";

export interface LlmActivity {
  request_id: string;
  source: "agent" | "sentinel";
  model?: string | null;
  phase: LlmActivityPhase;
  started_at: string;
  first_thinking_at?: string | null;
  last_thinking_at?: string | null;
  first_text_at?: string | null;
}

export interface LlmActivityUpdate {
  type: "llm_activity";
  activity?: LlmActivity | null;
}

export interface ToolCallInfo {
  type: "tool_call";
  tool: string;
  args: Record<string, unknown>;
  detail: string;
  contexts?: string[];
  approval_source?:
    | "safe-list"
    | "sentinel"
    | "user"
    | "skill"
    | "bypass"
    | "unknown";
  approval_verdict?: "allow" | "deny" | "escalate";
  approval_explanation?: string;
  tool_id?: string;
  parent_tool_id?: string;
}

export interface ToolResultInfo {
  type: "tool_result";
  tool: string;
  result: string;
  exit_code?: number;
  tool_id?: string;
}

export interface ApprovalRequest {
  type: "approval_request";
  tool_call_id: string;
  tool: string;
  args: Record<string, unknown>;
  explanation: string;
  risk_level: string;
}

export interface DomainAccessApprovalRequest {
  type: "domain_access_approval_request";
  request_id: string;
  domain: string;
  command: string;
}

export interface GitPushApprovalRequest {
  type: "git_push_approval_request";
  request_id: string;
  ref: string;
  explanation: string;
  changed_files: string[];
}

export interface CredentialApprovalRequest {
  type: "credential_approval_request";
  request_id: string;
  vault_paths: string[];
  names: string[];
  descriptions: string[];
  skill_name?: string;
  explanation: string;
}

/** Tiktoken prompt-mix percents for the last agent request (sum 100). */
export interface TurnUsageBreakdownPct {
  system: number;
  user: number;
  assistant: number;
  tool_calls: number;
  tool_returns: number;
  other: number;
}

export interface BudgetGauge {
  key: "input" | "output" | "cost";
  label: string;
  current_value: string;
  current_amount?: number | null;
  limit_value: string;
  remaining_value?: string | null;
  fill_pct: number;
  reached: boolean;
  unavailable_reason?: string | null;
}

export interface TurnUsage {
  input_tokens: number;
  output_tokens: number;
  breakdown_pct?: TurnUsageBreakdownPct | null;
  /** Canonical agent model id for this usage row (e.g. anthropic:claude-haiku-4-5). */
  model?: string | null;
  /** Backend-resolved context window for this usage row. */
  context_cap_tokens?: number | null;
  ttft_ms?: number | null;
  total_duration_ms?: number | null;
  reasoning_duration_ms?: number | null;
  reasoning_tokens?: number | null;
  started_at?: string | null;
  first_thinking_at?: string | null;
  last_thinking_at?: string | null;
  first_text_at?: string | null;
  completed_at?: string | null;
  /** Session budget gauges rendered below the context gauge. */
  budget_gauges?: BudgetGauge[];
}

export interface Done {
  type: "done";
  content: string;
  thinking?: string;
  usage?: TurnUsage;
}

export interface CommandResult {
  type: "command_result";
  command: string;
  data: unknown;
}

export interface ErrorMessage {
  type: "error";
  detail: string;
  turn_terminal?: boolean;
}

export interface Cancelled {
  type: "cancelled";
  detail: string;
}

export interface SessionTitleUpdate {
  type: "session_title";
  title: string;
  usage?: TurnUsage | null;
}

export interface StatusUpdate {
  type: "status";
  agent_running: boolean;
  usage?: TurnUsage;
  llm_activity?: LlmActivity | null;
}

export interface UserMessageNotification {
  type: "user_message";
  content: string;
}

export type ServerMessage =
  | TokenChunk
  | ThinkingChunk
  | ToolCallInfo
  | ToolResultInfo
  | ApprovalRequest
  | DomainAccessApprovalRequest
  | GitPushApprovalRequest
  | CredentialApprovalRequest
  | Done
  | CommandResult
  | ErrorMessage
  | Cancelled
  | SessionTitleUpdate
  | LlmActivityUpdate
  | StatusUpdate
  | UserMessageNotification;

// WebSocket protocol — Client → Server

export interface UserMessage {
  type: "message";
  content: string;
}

export interface ApprovalResponse {
  type: "approval_response";
  tool_call_id: string;
  approved: boolean;
  message?: string;
}

export type EscalationDecision = "allow" | "deny";

export interface EscalationResponse {
  type: "escalation_response";
  request_id: string;
  decision: EscalationDecision;
  message?: string;
}

export interface CancelRequest {
  type: "cancel";
}

export interface RetryLatestTurnRequest {
  type: "retry_latest_turn";
}

export interface ResetToTurnRequest {
  type: "reset_to_turn";
  event_index: number;
}

export type ClientMessage =
  | UserMessage
  | ApprovalResponse
  | EscalationResponse
  | CancelRequest
  | RetryLatestTurnRequest
  | ResetToTurnRequest;

// Chat UI messages

export type ChatMessage =
  | { kind: "user"; content: string }
  | { kind: "assistant"; content: string; eventIndex?: number }
  | { kind: "streaming"; content: string }
  | {
      kind: "thinking";
      content: string;
      reasoningDurationMs?: number;
      reasoningTokens?: number;
    }
  | {
      kind: "thinking_streaming";
      content: string;
      reasoningDurationMs?: number;
      reasoningTokens?: number;
    }
  | {
      kind: "tool_call";
      tool: string;
      args: Record<string, unknown>;
      detail: string;
      contexts?: string[];
      approvalSource?:
        | "safe-list"
        | "sentinel"
        | "user"
        | "skill"
        | "bypass"
        | "unknown";
      approvalVerdict?: "allow" | "deny" | "escalate";
      approvalExplanation?: string;
      decisionMessage?: string;
      result?: string;
      exitCode?: number;
      loading?: boolean;
      toolId?: string;
      parentToolId?: string;
      children?: Array<{
        kind: "tool_call";
        tool: string;
        args: Record<string, unknown>;
        detail: string;
        contexts?: string[];
        approvalSource?:
          | "safe-list"
          | "sentinel"
          | "user"
          | "skill"
          | "bypass"
          | "unknown";
        approvalVerdict?: "allow" | "deny" | "escalate";
        approvalExplanation?: string;
        decisionMessage?: string;
        result?: string;
        exitCode?: number;
        loading?: boolean;
        toolId?: string;
        parentToolId?: string;
      }>;
    }
  | { kind: "approval"; request: ApprovalRequest }
  | {
      kind: "domain_access_approval";
      request: DomainAccessApprovalRequest;
      decision?: EscalationDecision;
    }
  | {
      kind: "git_push_approval";
      request: GitPushApprovalRequest;
      decision?: EscalationDecision;
    }
  | {
      kind: "credential_approval";
      request: CredentialApprovalRequest;
      decision?: EscalationDecision;
    }
  | { kind: "command"; command: string; data: unknown }
  | {
      kind: "error";
      detail: string;
      eventIndex?: number;
      turnTerminal?: boolean;
    };
