// ICE Copilot (AI-1) frontend types — mirror the backend's safe capability
// metadata and the stable ICE SSE event contract. The frontend never sends or
// receives provider/model/identity fields.

export interface AssistantToolCapability {
  name: string;
  label: string;
}

export interface AssistantCapabilities {
  enabled: boolean;
  read_only: boolean;
  tools: AssistantToolCapability[];
  memory_enabled: boolean;
  memory_mode?: string;
  web_search_enabled: boolean;
  mutations_enabled: boolean;
}

export type AssistantEventName =
  | "assistant_start"
  | "assistant_token"
  | "tool_started"
  | "tool_finished"
  | "assistant_complete"
  | "approval_required"
  | "assistant_resumed"
  | "action_completed"
  | "error";

export interface AssistantEvent {
  event: AssistantEventName;
  data: Record<string, unknown>;
}

export interface AssistantChatRequest {
  message: string;
  thread_id?: string;
}

export interface AssistantResumeRequest {
  thread_id: string;
  decision: "approve" | "edit" | "reject" | "respond";
  // The tool name is ignored by the backend (it resolves the interrupted tool
  // from its own checkpoint state); only `args` are taken for edits.
  edited_action?: { name?: string; args: Record<string, unknown> };
  message?: string;
}

export interface ApprovalEditableField {
  label: string;
  type: "text" | "date" | "number";
  value: unknown;
}

export interface ApprovalRequest {
  thread_id: string;
  action_id: string;
  tool: string;
  summary: string;
  editable_fields: Record<string, ApprovalEditableField>;
  allowed_decisions: string[];
}

export interface AssistantRunDetails {
  model_calls?: number;
  tool_calls?: number;
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  took_ms?: number;
}

export interface ChatMessage {
  role: "user" | "assistant";
  text: string;
}

export interface ToolActivity {
  label: string;
  status: "active" | "done" | "error";
}
