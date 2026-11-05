import type { AgentName, Mode } from "@/lib/api";

type Meta = { label: string; text: string; bg: string; wash: string; border: string; blurb: string };

export const AGENT_META: Record<AgentName | "auto" | "system", Meta> = {
  auto: { label: "Auto", text: "text-ink", bg: "bg-ink", wash: "bg-sunken", border: "border-ink", blurb: "Picks the right agent for each message" },
  orchestrator: { label: "Coordinator", text: "text-orchestrator", bg: "bg-orchestrator", wash: "bg-sunken", border: "border-line", blurb: "" },
  research: { label: "Research", text: "text-research", bg: "bg-research", wash: "bg-research-wash", border: "border-research", blurb: "Searches the web and reasons over sources" },
  plan: { label: "Plan", text: "text-plan", bg: "bg-plan", wash: "bg-plan-wash", border: "border-plan", blurb: "Turns a goal into steps that can run" },
  execute: { label: "Execute", text: "text-execute", bg: "bg-execute", wash: "bg-execute-wash", border: "border-execute", blurb: "Runs the latest plan in a sandbox" },
  system: { label: "System", text: "text-muted", bg: "bg-muted", wash: "bg-sunken", border: "border-line", blurb: "" },
};

export const PLACEHOLDER: Record<Mode, string> = {
  auto: "Ask anything, or describe something you want done",
  research: "What should I look into?",
  plan: "What's the goal? I'll use any research from this chat",
  execute: "Send to run the latest plan (say “dry run” to preview)",
};
