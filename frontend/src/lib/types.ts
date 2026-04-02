// Session

export interface SessionInfo {
  session_id: string;
  channel_type: string;
  channel_ref: string;
  created_at: string;
  last_active: string;
  title?: string;
  activated_rules: string[];
  disabled_rules: string[];
  message_count: number;
}

export interface HistoryMessage {
  role: string;
  content: string;
  tool?: string;
  args?: Record<string, unknown>;
  detail?: string;
  result?: string;
  exit_code?: number;
  command?: string;
  data?: unknown;
  request_id?: string;
  domain?: string;
  decision?: string;
  tool_call_id?: string;
  explanation?: string;
  risk_level?: string;
  ref?: string;
  changed_files?: string[];
  vault_paths?: string[];
  names?: string[];
  descriptions?: string[];
  skill_name?: string;
}

// WebSocket protocol — Server → Client

export interface TokenChunk {
  type: "token";
  content: string;
}

export interface ToolCallInfo {
  type: "tool_call";
  tool: string;
  args: Record<string, unknown>;
  detail: string;
}

export interface ToolResultInfo {
  type: "tool_result";
  tool: string;
  result: string;
  exit_code?: number;
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

export interface TurnUsage {
  input_tokens: number;
  output_tokens: number;
}

export interface Done {
  type: "done";
  content: string;
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
}

export interface Cancelled {
  type: "cancelled";
  detail: string;
}

export interface SessionTitleUpdate {
  type: "session_title";
  title: string;
}

export interface StatusUpdate {
  type: "status";
  agent_running: boolean;
  usage?: TurnUsage;
}

export interface UserMessageNotification {
  type: "user_message";
  content: string;
}

export type ServerMessage =
  | TokenChunk
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
}

export type EscalationDecision = "allow" | "deny";

export interface EscalationResponse {
  type: "escalation_response";
  request_id: string;
  decision: EscalationDecision;
}

export type CredentialDecision = "approved" | "denied";

export interface CredentialApprovalResponse {
  type: "credential_approval_response";
  vault_paths: string[];
  decision: CredentialDecision;
}

export interface CancelRequest {
  type: "cancel";
}

export type ClientMessage =
  | UserMessage
  | ApprovalResponse
  | EscalationResponse
  | CredentialApprovalResponse
  | CancelRequest;

// Chat UI messages

export type ChatMessage =
  | { kind: "user"; content: string }
  | { kind: "assistant"; content: string }
  | { kind: "streaming"; content: string }
  | {
      kind: "tool_call";
      tool: string;
      args: Record<string, unknown>;
      detail: string;
      result?: string;
      exitCode?: number;
      loading?: boolean;
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
      decision?: CredentialDecision;
    }
  | { kind: "command"; command: string; data: unknown }
  | { kind: "error"; detail: string };
