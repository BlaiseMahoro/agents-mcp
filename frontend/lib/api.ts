// Typed client for the FastAPI backend, including the SSE event stream.

export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type AgentName = "research" | "plan" | "execute" | "orchestrator";
export type Mode = "auto" | "research" | "plan" | "execute";
export const SPECIALISTS = ["research", "plan", "execute"] as const;
export type Specialist = (typeof SPECIALISTS)[number];

export type AgentEvent = {
  type: string;
  agent: AgentName | null;
  // Payload shape depends on `type` (see backend schemas.AgentEvent); narrowed in lib/turn.ts.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: Record<string, any>;
};

export type Source = { title: string; url: string };

export type ResearchReport = {
  id?: string;
  question: string;
  answer_markdown: string;
  key_findings: string[];
  sources: Source[];
  open_questions: string[];
};

export type Message = {
  id: string;
  role: "user" | "assistant";
  mode: string;
  content: string;
  events: AgentEvent[];
  pending?: boolean;
};

export type Conversation = { id: string; title: string; updated_at: string };

export type Step = {
  id: string;
  type: "shell" | "write_file" | "read_file" | "llm_task";
  description: string;
  depends_on: string[];
  on_failure: "stop" | "continue";
  command?: string;
  path?: string;
  content?: string;
  prompt?: string;
  inputs_from?: string[];
};

export type Plan = {
  id: string;
  goal: string;
  summary: string;
  assumptions: string[];
  steps: Step[];
  status: "draft" | "approved" | "running" | "succeeded" | "failed" | "cancelled";
  conversation_id: string | null;
};

export type AgentModel = { provider: string; model: string; effort?: string; search?: string; max_searches?: number };

export type Settings = {
  enabled: Record<Specialist, boolean>;
  require_approval: boolean;
  agents: Record<string, AgentModel>;
  providers: string[];
};

export type Health = {
  docker: Check;
  sandbox_image: Check;
  searxng: Check;
  providers: Record<string, Check>;
};
type Check = { ok: boolean; detail: string };

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  } catch {
    throw new ApiError(0, `Can't reach the backend at ${API}. Start it with \`make api\`.`);
  }
  if (!res.ok) throw new ApiError(res.status, await errorText(res));
  return res.json();
}

async function errorText(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map((d: { loc?: unknown[]; msg: string }) => `${(d.loc ?? []).join(".")}: ${d.msg}`).join("\n");
  } catch {}
  return `Request failed (${res.status})`;
}

export const api = {
  conversations: () => json<Conversation[]>("/api/conversations"),
  createConversation: () => json<Conversation>("/api/conversations", { method: "POST" }),
  conversation: (id: string) => json<Conversation & { messages: Message[] }>(`/api/conversations/${id}`),
  deleteConversation: (id: string) => json(`/api/conversations/${id}`, { method: "DELETE" }),
  settings: () => json<Settings>("/api/settings"),
  saveSettings: (patch: Partial<Omit<Settings, "agents">> & { agents?: Record<string, Partial<AgentModel>> }) =>
    json<Settings>("/api/settings", { method: "PUT", body: JSON.stringify(patch) }),
  models: () => json<Record<string, string[]>>("/api/models"),
  health: () => json<Health>("/api/health"),
  plan: (id: string) => json<Plan>(`/api/plans/${id}`),
  savePlan: (id: string, body: Partial<Plan>) => json<Plan>(`/api/plans/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  cancelRun: (id: string) => json(`/api/runs/${id}/cancel`, { method: "POST" }),
};

/** POST and read a Server-Sent Events stream of AgentEvents. */
export async function streamEvents(path: string, body: unknown, onEvent: (e: AgentEvent) => void, signal?: AbortSignal) {
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") return;
    throw new ApiError(0, `Can't reach the backend at ${API}. Start it with \`make api\`.`);
  }
  if (!res.ok || !res.body) throw new ApiError(res.status, await errorText(res));

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value.replace(/\r\n/g, "\n");
    let cut;
    while ((cut = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      const data = frame
        .split("\n")
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).trimStart())
        .join("\n");
      if (data) onEvent(JSON.parse(data));
    }
  }
}
