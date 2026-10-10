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
  memory_enabled: boolean;
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

// Memory (/api/memory). Mirrors src/carapace/memory/models.py.
// Decimal amounts arrive as strings, datetimes and dates as ISO strings.

export type MemoryTaskKind = "session_extract" | "week_digest" | "month_digest" | "mirror";
export type MemoryTaskStatus = "pending" | "queued" | "running" | "done" | "failed" | "cancelled";
export type MemoryBlockedReason = "budget";
export type MemorySpawnedBy = "auto" | "manual";
export type MemoryModelRole = "memory_low" | "memory_high";
export type MemoryDigestLevel = "week" | "month";
export type MemoryFactCategory = "user" | "social" | "surroundings";
export type MemoryFactSourceKind = "user_said" | "observed";
export type MemoryConfidence = "low" | "medium" | "high";
export type MemoryDurability = "durable" | "dated";
export type MemoryOutdatedReason = "prompt_version" | "model" | "input_format_version";
export type MemoryExtractionState = "missing" | "current" | "outdated";

export interface MemoryFact {
  category: MemoryFactCategory;
  statement: string;
  subject: string | null;
  source_seqs: number[];
  source_kind: MemoryFactSourceKind;
  confidence: MemoryConfidence;
  durability: MemoryDurability;
  valid_until: string | null;
}

export interface MemorySessionExtraction {
  abstract: string;
  outcomes: string[];
  open_loops: string[];
  on_my_mind: string[];
  facts: MemoryFact[];
  friction: string[];
  tags: string[];
}

export interface MemoryDigestTheme {
  theme: string;
  /** Session ids (week digests) or week keys (month digests). */
  refs: string[];
}

/** A deduplicated fact; user_said only if every merged source was. */
export interface MemoryDigestFact {
  category: MemoryFactCategory;
  statement: string;
  subject: string | null;
  source_kind: MemoryFactSourceKind;
  confidence: MemoryConfidence;
  durability: MemoryDurability;
  valid_until: string | null;
  /** Session ids (week digests) or week keys (month digests). */
  refs: string[];
}

export interface MemoryPeriodDigest {
  summary: string;
  on_my_mind: MemoryDigestTheme[];
  highlights: string[];
  open_loops: string[];
  learned: MemoryDigestFact[];
}

export interface MemoryProvenance {
  carapace_version: string;
  model: string;
  prompt_version: string;
  input_format_version: number;
  input_hash: string;
  input_tokens: number;
  output_tokens: number;
  /** null when the model has no known pricing. */
  cost_usd: string | null;
  duration_ms: number;
  task_id: number;
  created_at: string;
}

export interface MemoryTaskEstimate {
  model: string;
  input_tokens: number;
  output_tokens_cap: number;
  cost_usd: string | null;
}

export interface MemoryCoverageEntry {
  source_id: string;
  source_hash: string;
}

export interface MemoryTask {
  id: number;
  user: string;
  kind: MemoryTaskKind;
  target: string;
  status: MemoryTaskStatus;
  blocked_reason: MemoryBlockedReason | null;
  spawned_by: MemorySpawnedBy;
  model_override: string | null;
  attempts: number;
  estimate: MemoryTaskEstimate | null;
  provenance: MemoryProvenance | null;
  result_id: number | null;
  error: string | null;
  created_at: string;
  queued_at: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface MemoryTaskView extends MemoryTask {
  target_label: string;
}

export interface MemoryExtractionRecord {
  id: number;
  session_id: string;
  week_key: string;
  month_key: string;
  is_current: boolean;
  input_hash: string;
  provenance: MemoryProvenance;
  extraction: MemorySessionExtraction;
  created_at: string;
}

export interface MemoryDigestRecord {
  id: number;
  level: MemoryDigestLevel;
  period_key: string;
  is_current: boolean;
  coverage: MemoryCoverageEntry[];
  coverage_hash: string;
  provenance: MemoryProvenance;
  digest: MemoryPeriodDigest;
  created_at: string;
}

export interface MemoryBudgetWindowStatus {
  window_start: string;
  spent_cost_usd: string;
  spent_input_tokens: number;
  limit_cost_usd: string | null;
  limit_input_tokens: number | null;
}

export interface MemoryStatus {
  auto_mode: boolean;
  timezone: string;
  day: MemoryBudgetWindowStatus;
  month: MemoryBudgetWindowStatus;
  queue: Record<MemoryTaskStatus, number>;
  /** Queued tasks held back by the budget gate. */
  blocked: number;
  models: Record<MemoryModelRole, string>;
}

/** GET /tasks query params (lists repeat the param) and the `filter` of a selection. */
export interface MemoryTaskFilter {
  status?: MemoryTaskStatus[] | null;
  kind?: MemoryTaskKind[] | null;
  /** Week (2026-W36) or month (2026-09) key. */
  period?: string | null;
  model?: string | null;
}

/** Exactly one of ids or filter; newest limits a filter to its newest N. */
export interface MemoryTaskSelection {
  ids?: number[] | null;
  filter?: MemoryTaskFilter | null;
  newest?: number | null;
}

/** Body of POST /tasks/estimate and POST /tasks/run. */
export interface MemoryTaskRunRequest {
  selection: MemoryTaskSelection;
  model_override?: string | null;
}

/** Body of POST /tasks/retry. */
export interface MemoryTaskIdsRequest {
  ids: number[];
}

/** Body of POST /tasks/spawn: explicit targets, or (session_extract only) every session matching a filter. */
export interface MemoryTaskSpawnRequest {
  kind: MemoryTaskKind;
  targets?: string[] | null;
  filter?: MemorySessionFilter | null;
  model_override?: string | null;
}

export interface MemoryTaskCountResponse {
  count: number;
}

export interface MemoryTaskSpawnResponse {
  task_ids: number[];
}

export interface MemoryEstimateTotal {
  task_count: number;
  input_tokens: number;
  output_tokens_cap: number;
  /** Sum over priced tasks; unpriced_count tasks had no known pricing. */
  cost_usd: string;
  unpriced_count: number;
}

export interface MemoryTaskListResponse {
  items: MemoryTaskView[];
  next_cursor: string | null;
  total: number;
  estimate: MemoryEstimateTotal;
}

export interface MemoryTaskRef {
  id: number;
  status: MemoryTaskStatus;
  blocked_reason: MemoryBlockedReason | null;
}

export interface MemoryFactCounts {
  user: number;
  social: number;
  surroundings: number;
}

export interface MemoryExtractionSummary {
  id: number;
  abstract: string;
  fact_counts: MemoryFactCounts;
  model: string;
  prompt_version: string;
  cost_usd: string | null;
  created_at: string;
  /** Empty when current. */
  outdated: MemoryOutdatedReason[];
}

/** GET /sessions query params. */
export interface MemorySessionFilter {
  week?: string | null;
  state?: MemoryExtractionState[] | null;
  task_status?: MemoryTaskStatus[] | null;
  model?: string | null;
  channel?: string | null;
  /** Matched against the current extraction, for bulk respawns. */
  outdated_reason?: MemoryOutdatedReason | null;
}

export interface MemorySessionRow {
  session_id: string;
  title: string | null;
  channel_type: string;
  created_at: string;
  /** From the current extraction or the open task; null until first spawned. */
  week_key: string | null;
  extraction: MemoryExtractionSummary | null;
  task: MemoryTaskRef | null;
}

export interface MemorySessionListResponse {
  items: MemorySessionRow[];
  next_cursor: string | null;
  total: number;
}

export interface MemorySessionDetail {
  session: MemorySessionRow;
  current: MemoryExtractionRecord | null;
  /** Earlier extractions, newest first. */
  history: MemoryExtractionRecord[];
}

export interface MemoryDigestSummary {
  id: number;
  model: string;
  prompt_version: string;
  carapace_version: string;
  cost_usd: string | null;
  created_at: string;
  /** Empty when current. */
  outdated: MemoryOutdatedReason[];
}

export interface MemoryPeriodNode {
  level: MemoryDigestLevel;
  key: string;
  start: string;
  end: string;
  /** Week: extracted/eligible sessions. Month: weeks with a current digest/weeks. */
  covered: number;
  total: number;
  digest: MemoryDigestSummary | null;
  /** Current digest's coverage no longer matches the period's sources. */
  stale: boolean;
  task: MemoryTaskRef | null;
}

export interface MemoryMonthNode extends MemoryPeriodNode {
  weeks: MemoryPeriodNode[];
}

export interface MemoryPeriodTree {
  months: MemoryMonthNode[];
}

export interface MemoryPeriodDetail {
  node: MemoryPeriodNode;
  current: MemoryDigestRecord | null;
  history: MemoryDigestRecord[];
  /** Sources: sessions for a week, weeks for a month (the other list is empty). */
  sessions: MemorySessionRow[];
  weeks: MemoryPeriodNode[];
}

/** GET /facts query params. */
export interface MemoryFactFilter {
  category?: MemoryFactCategory[] | null;
  subject?: string | null;
  confidence?: MemoryConfidence[] | null;
  durability?: MemoryDurability[] | null;
  source_kind?: MemoryFactSourceKind[] | null;
  period?: string | null;
}

export interface MemoryFactView {
  id: number;
  extraction_id: number;
  session_id: string;
  session_title: string | null;
  category: MemoryFactCategory;
  subject: string | null;
  statement: string;
  source_kind: MemoryFactSourceKind;
  confidence: MemoryConfidence;
  durability: MemoryDurability;
  valid_until: string | null;
  source_seqs: number[];
  week_key: string;
  created_at: string;
}

export interface MemoryFactListResponse {
  items: MemoryFactView[];
}
