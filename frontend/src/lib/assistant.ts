// ICE Copilot (AI-1) — capabilities fetch + SSE streaming transport.
//
// The backend emits a STABLE ICE event contract (assistant_start,
// assistant_token, tool_started, tool_finished, assistant_complete, error).
// This module translates the raw SSE bytes into typed AssistantEvents and is
// deliberately decoupled from any LangChain/LangGraph event names.
import {
  API_URL,
  api,
  getAccessToken,
} from "./api";
import type {
  AssistantCapabilities,
  AssistantChatRequest,
  AssistantEvent,
  AssistantEventName,
} from "../types/assistant";

const KNOWN_EVENTS: ReadonlySet<string> = new Set<AssistantEventName>([
  "assistant_start",
  "assistant_token",
  "tool_started",
  "tool_finished",
  "assistant_complete",
  "error",
]);

export async function getCapabilities(): Promise<AssistantCapabilities> {
  const { data } = await api.get<AssistantCapabilities>("/assistant/capabilities");
  return data;
}

export class AssistantRequestError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function parseSseFrame(raw: string): AssistantEvent | null {
  let event: string | null = null;
  let data: string | null = null;
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) {
      event = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      data = line.slice("data:".length).trim();
    }
  }
  if (!event || !KNOWN_EVENTS.has(event) || data === null) {
    return null; // unknown events and malformed frames are safely ignored
  }
  try {
    return { event: event as AssistantEventName, data: JSON.parse(data) as Record<string, unknown> };
  } catch {
    return null; // malformed JSON is safely ignored
  }
}

/**
 * Stream one assistant turn as an async generator of ICE events.
 *
 * Uses fetch + ReadableStream (NOT EventSource: chat is POST + Bearer auth).
 * The SSE parser tolerates events split across network chunks, several events
 * in one chunk, blank-line termination, and malformed/unknown frames.
 */
export async function* streamChat(
  message: string,
  signal?: AbortSignal
): AsyncGenerator<AssistantEvent> {
  const token = getAccessToken();
  const response = await fetch(`${API_URL}/assistant/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ message } satisfies AssistantChatRequest),
    signal,
  });

  if (!response.ok || !response.body) {
    if (response.status === 401) {
      throw new AssistantRequestError(401, "Your session has expired. Please sign in again.");
    }
    if (response.status === 503) {
      throw new AssistantRequestError(503, "The ICE Copilot is not enabled.");
    }
    if (response.status === 429) {
      throw new AssistantRequestError(429, "Too many requests. Please wait a moment and try again.");
    }
    throw new AssistantRequestError(response.status, "The assistant could not be reached.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const event = parseSseFrame(frame);
        if (event) {
          yield event;
        }
        boundary = buffer.indexOf("\n\n");
      }
    }
    // Flush any final frame that did not end with a blank line.
    const trailing = buffer.trim();
    if (trailing) {
      const event = parseSseFrame(trailing);
      if (event) {
        yield event;
      }
    }
  } finally {
    if (signal?.aborted) {
      // Best-effort cancellation of the underlying stream on abort.
      void reader.cancel().catch(() => undefined);
    }
  }
}
