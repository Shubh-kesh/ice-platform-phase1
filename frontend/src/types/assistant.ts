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
  web_search_enabled: boolean;
  mutations_enabled: boolean;
}

export type AssistantEventName =
  | "assistant_start"
  | "assistant_token"
  | "tool_started"
  | "tool_finished"
  | "assistant_complete"
  | "error";

export interface AssistantEvent {
  event: AssistantEventName;
  data: Record<string, unknown>;
}

export interface AssistantChatRequest {
  message: string;
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
