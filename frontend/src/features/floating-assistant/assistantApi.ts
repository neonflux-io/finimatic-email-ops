const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const SESSION_KEY = "va_session_token";

export type AgentModel = "auto" | "groq" | "gemini";

export type AgentDraft = {
  draft_id: string;
  contact_id: string;
  to: string;
  subject: string;
  body: string;
  warnings: string[];
};

export type PendingAction = {
  action_id: string;
  capability: string;
  draft_id: string;
  contact_id: string;
  to: string;
  subject: string;
  body: string;
  confirmation_prompt: string;
  expires_at: string;
};

export type AgentChatResponse = {
  response: string;
  source?: string | null;
  intent?: string | null;
  is_clarification: boolean;
  draft?: AgentDraft | null;
  pending_action?: PendingAction | null;
  error_code?: string | null;
};

export type AttachmentPayload = {
  id: string;
  name: string;
  size: number;
  mimeType: string;
  kind: string;
};

function makeId(prefix: string) {
  if (crypto.randomUUID) return `${prefix}_${crypto.randomUUID()}`;
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

export function getSessionToken() {
  const existing = sessionStorage.getItem(SESSION_KEY);
  if (existing) return existing;
  const next = makeId("session");
  sessionStorage.setItem(SESSION_KEY, next);
  return next;
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {})
    }
  });
  const text = await response.text();
  let parsed: any = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = null;
  }
  if (!response.ok) {
    if (parsed && typeof parsed === "object" && "response" in parsed) return parsed as T;
    if (parsed?.detail && typeof parsed.detail === "object" && "response" in parsed.detail) return parsed.detail as T;
    const reason = typeof parsed?.detail === "string" ? parsed.detail : `request_failed_${response.status}`;
    throw new Error(reason);
  }
  return parsed as T;
}

export const assistantApi = {
  chat: (payload: { session_token: string; message: string; provider: AgentModel; attachments?: AttachmentPayload[] }) =>
    request<AgentChatResponse>("/api/agent/chat", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  confirm: (session_token: string, action_id: string) =>
    request<AgentChatResponse>("/api/agent/confirm", {
      method: "POST",
      body: JSON.stringify({ session_token, action_id })
    }),
  cancel: (session_token: string) =>
    request<AgentChatResponse>("/api/agent/cancel", {
      method: "DELETE",
      body: JSON.stringify({ session_token })
    })
};
