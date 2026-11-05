// Folds a flat AgentEvent stream into renderable blocks, grouped into agent lanes.

import type { AgentEvent, AgentName, Plan, ResearchReport, Source } from "./api";

export type ToolInput = { query?: string; url?: string; [key: string]: unknown } | null;

export type StepState = {
  id: string;
  type?: string;
  description?: string;
  status: string;
  output: string;
  error?: string;
  exit_code?: number | null;
  duration_s?: number;
};

export type Block =
  | { kind: "text"; text: string }
  | { kind: "thinking"; text: string }
  | { kind: "tool"; name: string; input: ToolInput; results?: Source[]; error?: boolean }
  | { kind: "research"; report: ResearchReport }
  | { kind: "plan"; plan: Plan }
  | { kind: "approval"; planId: string }
  | { kind: "run"; runId: string; planId: string; dryRun: boolean; order: string[]; steps: Record<string, StepState>; status: string }
  | { kind: "error"; message: string };

export type Lane = { agent: AgentName | "system"; blocks: Block[] };

export function buildLanes(events: AgentEvent[]): Lane[] {
  const lanes: Lane[] = [];
  const runs = new Map<string, Extract<Block, { kind: "run" }>>();

  const lane = (agent: AgentName | null): Lane => {
    const name = agent ?? "system";
    const last = lanes[lanes.length - 1];
    if (last && last.agent === name) return last;
    const l: Lane = { agent: name, blocks: [] };
    lanes.push(l);
    return l;
  };
  const push = (agent: AgentName | null, b: Block) => lane(agent).blocks.push(b);
  const lastBlock = (agent: AgentName | null) => {
    const bs = lane(agent).blocks;
    return bs[bs.length - 1];
  };

  for (const ev of events) {
    const d = ev.data;
    switch (ev.type) {
      case "text_delta": {
        const b = lastBlock(ev.agent);
        if (b?.kind === "text") b.text += d.delta;
        else push(ev.agent, { kind: "text", text: d.delta });
        break;
      }
      case "thinking": {
        const b = lastBlock(ev.agent);
        if (b?.kind === "thinking") b.text += d.delta;
        else push(ev.agent, { kind: "thinking", text: d.delta });
        break;
      }
      case "tool_call":
        // The orchestrator's calls to specialists show up as the specialist's own lane instead.
        if (!(ev.agent === "orchestrator" && ["research", "create_plan", "execute_plan"].includes(d.name)))
          push(ev.agent, { kind: "tool", name: d.name, input: d.input });
        break;
      case "search_result": {
        const b = lastBlock(ev.agent);
        if (b?.kind === "tool" && !b.results) b.results = d.results;
        else push(ev.agent, { kind: "tool", name: "web_search", input: { query: d.query }, results: d.results });
        break;
      }
      case "tool_result": {
        const b = lastBlock(ev.agent);
        if (b?.kind === "tool" && d.is_error) b.error = true;
        break;
      }
      case "research_report":
        push(ev.agent, { kind: "research", report: d as ResearchReport });
        break;
      case "plan_ready":
        push(ev.agent, { kind: "plan", plan: d as Plan });
        break;
      case "approval_required":
        push(ev.agent, { kind: "approval", planId: d.plan_id });
        break;
      case "run_start": {
        const steps: Record<string, StepState> = {};
        for (const id of d.steps) steps[id] = { id, status: "pending", output: "" };
        const run = { kind: "run" as const, runId: d.run_id, planId: d.plan_id, dryRun: d.dry_run, order: d.steps, steps, status: "running" };
        runs.set(d.run_id, run);
        push(ev.agent, run);
        break;
      }
      case "step_start":
      case "step_output":
      case "step_end": {
        const run = [...runs.values()].at(-1);
        if (!run) break;
        const s = (run.steps[d.step_id] ??= { id: d.step_id, status: "pending", output: "" });
        if (ev.type === "step_start") Object.assign(s, { status: "running", type: d.type, description: d.description });
        if (ev.type === "step_output") s.output += d.text;
        if (ev.type === "step_end") Object.assign(s, { status: d.status, output: d.output || s.output, error: d.error, exit_code: d.exit_code, duration_s: d.duration_s });
        break;
      }
      case "run_end": {
        const run = runs.get(d.run_id);
        if (run) run.status = d.status;
        break;
      }
      case "error":
        push(ev.agent, { kind: "error", message: d.message });
        break;
    }
  }
  return lanes.filter((l) => l.blocks.length > 0);
}
