// Notifications

export interface NotificationPreferences {
  escalation_pending: boolean;
  attended_turn_completed: boolean;
  unattended_turn_completed: boolean;
  unattended_turn_failed: boolean;
}

export interface NotificationPreferencesPatch {
  escalation_pending?: boolean;
  attended_turn_completed?: boolean;
  unattended_turn_completed?: boolean;
  unattended_turn_failed?: boolean;
}

export interface NotificationSubscriptionCreateRequest {
  endpoint: string;
  p256dh: string;
  auth: string;
  device_name: string;
  preferences?: NotificationPreferencesPatch;
}

export interface NotificationSubscriptionRecord {
  subscription_id: string;
  device_name: string;
  endpoint: string;
  subscribed_at: string;
  expires_at: string;
  last_heartbeat?: string | null;
  preferences: NotificationPreferences;
}

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
  sandbox_id?: string | null;
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
  unattended: boolean;
  ask_mode: boolean;
  yolo_mode: boolean;
}

export interface SessionAttributesPatch {
  private?: boolean;
  archived?: boolean;
  pinned?: boolean;
  favorite?: boolean;
  unattended?: boolean;
  ask_mode?: boolean;
  yolo_mode?: boolean;
}

export interface SessionInfo {
  session_id: string;
  channel_type: string;
  channel_ref: string | null;
  created_at: string;
  last_active: string;
  title?: string;
  agent_model_name?: string | null;
  sentinel_model_name?: string | null;
  attributes: SessionAttributes;
  latest_job_run?: SessionLatestJobRun | null;
  knowledge_last_committed_at?: string | null;
  knowledge_last_archive_path?: string | null;
  knowledge_last_commit_trigger?: string | null;
  activated_rules: string[];
  disabled_rules: string[];
  message_count: number;
  total_cost_usd?: number | null;
  sandbox?: SessionSandboxSnapshot | null;
}

export interface SessionLatestJobRun {
  job_id: string;
  trigger_kind: "api" | "cron" | "manual";
  triggered_at: string;
  data?: string | null;
  cron_expression?: string | null;
}

export interface SessionListPage {
  items: SessionInfo[];
  next_cursor?: string | null;
  has_more: boolean;
}

export interface SessionArchiveCommitResponse {
  session: SessionInfo;
  committed: boolean;
  archive_path?: string | null;
  committed_at?: string | null;
  trigger: string;
  reason?: string | null;
}

// Jobs

export interface JobCronTrigger {
  type: "cron";
  expression: string;
  timezone?: string | null;
}

export interface JobDefinition {
  id: string;
  name: string;
  enabled: boolean;
  triggers: JobCronTrigger[];
  prompt: string;
  private: boolean;
  unattended: boolean;
  ask_mode: boolean;
  yolo_mode: boolean;
  archive_previous_sessions: boolean;
  persistent_session_id?: string | null;
  agent_model_name?: string | null;
  sentinel_model_name?: string | null;
  title_model_name?: string | null;
}

export interface JobsFile {
  jobs: JobDefinition[];
}

export interface JobRunResult {
  job_id: string;
  session_id: string;
  created_new_session: boolean;
  session: SessionInfo;
}

export interface Attachment {
  name: string;
  path: string;
  file_id?: string;
  size?: number;
  mime?: string;
}

export interface SentFile {
  file_id: string;
  name: string;
  mime: string;
  size: number;
}

export interface HistoryMessage {
  role: string;
  content: string;
  attachments?: Attachment[];
  final_status?: "success" | "warning";
  event_index?: number;
  timestamp?: string;
  usage?: {
    model?: string | null;
    input_tokens?: number;
    output_tokens?: number;
    ttft_ms?: number | null;
    generation_ms?: number | null;
  };
  partial?: boolean;
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
  files?: SentFile[];
  exit_code?: number;
  command?: string;
  data?: unknown;
  request_id?: string;
  domain?: string;
  decision?: string;
  tool_call_id?: string;
  decision_source?: "user" | "system";
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
  compaction?: CompactionAnnotation;
}

/**
 * Compaction annotation attached to a history event:
 * - `{ folded_into, summary }` on a user/assistant/tool event folded into a summary node
 * - `{ method, orig_tokens, summary_tokens, model_text }` on a compacted tool_result
 *
 * `summary` / `model_text` carry the model-facing text so the main (uncompacted) view can show,
 * on demand, exactly what the model sees for a folded run or a shortened tool output.
 */
export interface CompactionAnnotation {
  folded_into?: string;
  summary?: string;
  method?: "truncate" | "summarize" | "drop";
  orig_tokens?: number;
  summary_tokens?: number;
  model_text?: string;
}

export interface AgentHistoryRow {
  role:
    | "user"
    | "assistant"
    | "thinking"
    | "tool_call"
    | "tool_result"
    | "compaction_summary";
  content: string;
  tool?: string;
  args?: Record<string, unknown>;
  tool_id?: string;
  compaction?: CompactionAnnotation;
}

export interface AgentHistoryResponse {
  rows: AgentHistoryRow[];
  node_count: number;
}

export interface CompactionReport {
  mode: "all" | "fold" | "tools";
  before_tokens: number;
  after_tokens: number;
  thinking_dropped: number;
  turns_folded: number;
  tool_returns_compacted: number;
  consolidated: boolean;
  message: string;
  error?: string;
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
  files?: SentFile[];
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
  key: "input" | "output" | "cost" | "tool_calls";
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
  final_status?: "success" | "warning";
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
  attachments?: Attachment[];
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
  attachments?: Attachment[];
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
  | {
      kind: "user";
      content: string;
      attachments?: Attachment[];
      compaction?: CompactionAnnotation;
      timestamp?: string;
      turnIndex?: number;
      eventIndex?: number;
    }
  | {
      kind: "assistant";
      content: string;
      eventIndex?: number;
      finalStatus?: "success" | "warning";
      compaction?: CompactionAnnotation;
      timestamp?: string;
      turnIndex?: number;
      turnDurationMs?: number;
      toolCount?: number;
      model?: string;
      inputTokens?: number;
      outputTokens?: number;
      ttftMs?: number;
      generationMs?: number;
      /** Intermediate narration emitted before a tool call, not the turn's final answer. */
      partial?: boolean;
      /** 1-based position of this assistant bubble within its turn, and the turn's total. */
      messageIndexInTurn?: number;
      turnMessageCount?: number;
    }
  | {
      kind: "compaction_summary";
      nodeId: string;
      foldedCount: number;
      /** Turns (not raw messages) the fold covers, for the rail header label. */
      turnCount: number;
      /** Model-facing summary text shown when the rail header is expanded. */
      summary?: string;
      origTokens?: number;
      summaryTokens?: number;
      children: ChatMessage[];
    }
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
      files?: SentFile[];
      exitCode?: number;
      loading?: boolean;
      toolId?: string;
      parentToolId?: string;
      compaction?: CompactionAnnotation;
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
        files?: SentFile[];
        exitCode?: number;
        loading?: boolean;
        toolId?: string;
        parentToolId?: string;
        compaction?: CompactionAnnotation;
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
  | { kind: "command"; command: string; data: unknown; live?: boolean }
  | {
      kind: "error";
      detail: string;
      eventIndex?: number;
      turnTerminal?: boolean;
    };
