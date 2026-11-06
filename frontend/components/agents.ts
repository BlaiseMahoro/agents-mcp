import type { AgentName, Mode } from "@/lib/api";

type Meta = { label: string; sigil: string; text: string; bg: string; wash: string; border: string; blurb: string };

// The app's agents, in the Wizard's terms. Internal names (research/plan/execute) stay unchanged.
export const AGENT_META: Record<AgentName | "auto" | "system", Meta> = {
  auto: { label: "Wizard", sigil: "✶", text: "text-ink", bg: "bg-ink", wash: "bg-sunken", border: "border-ink", blurb: "Decides which of the three to send" },
  orchestrator: { label: "Wizard", sigil: "✶", text: "text-orchestrator", bg: "bg-orchestrator", wash: "bg-sunken", border: "border-line", blurb: "" },
  research: { label: "Seer", sigil: "☽", text: "text-research", bg: "bg-research", wash: "bg-research-wash", border: "border-research", blurb: "Searches the web and weighs the sources" },
  plan: { label: "Scribe", sigil: "☿", text: "text-plan", bg: "bg-plan", wash: "bg-plan-wash", border: "border-plan", blurb: "Writes a spell: the steps to get it done" },
  execute: { label: "Conjurer", sigil: "☉", text: "text-execute", bg: "bg-execute", wash: "bg-execute-wash", border: "border-execute", blurb: "Casts the spell in a sealed sandbox" },
  system: { label: "System", sigil: "·", text: "text-muted", bg: "bg-muted", wash: "bg-sunken", border: "border-line", blurb: "" },
};

export const PLACEHOLDER: Record<Mode, string> = {
  auto: "Ask the Wizard anything, or describe what you want done",
  research: "What should the Seer look into?",
  plan: "What should the spell achieve? The Scribe uses anything the Seer found",
  execute: "Send to cast the latest spell (say “dry run” to preview it)",
};
