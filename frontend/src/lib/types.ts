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
  command?: string;
  data?: unknown;
  request_id?: string;
  domain?: string;
  decision?: string;
  tool_call_id?: string;
  explanation?: string;
  risk_level?: string;
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
}

export interface ApprovalRequest {
  type: "approval_request";
  tool_call_id: string;
  tool: string;
  args: Record<string, unknown>;
  explanation: string;
  risk_level: string;
}

export interface ProxyApprovalRequest {
  type: "proxy_approval_request";
  request_id: string;
  domain: string;
  command: string;
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

export type ServerMessage =
  | TokenChunk
  | ToolCallInfo
  | ToolResultInfo
  | ApprovalRequest
  | ProxyApprovalRequest
  | Done
  | CommandResult
  | ErrorMessage
  | Cancelled
  | SessionTitleUpdate;

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

export type DomainDecision = "allow" | "deny";

export interface ProxyApprovalResponse {
  type: "proxy_approval_response";
  request_id: string;
  decision: DomainDecision;
}

export interface CancelRequest {
  type: "cancel";
}

export type ClientMessage =
  | UserMessage
  | ApprovalResponse
  | ProxyApprovalResponse
  | CancelRequest;

// Chat UI messages

export type ChatMessage =
  | { kind: "user"; content: string }
  | { kind: "assistant"; content: string }
  | {
      kind: "tool_call";
      tool: string;
      args: Record<string, unknown>;
      detail: string;
      result?: string;
      loading?: boolean;
    }
  | { kind: "approval"; request: ApprovalRequest }
  | {
      kind: "proxy_approval";
      request: ProxyApprovalRequest;
      decision?: DomainDecision;
    }
  | { kind: "command"; command: string; data: unknown }
  | { kind: "error"; detail: string };
