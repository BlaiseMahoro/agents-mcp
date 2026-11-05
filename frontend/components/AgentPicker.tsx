"use client";

import type { Mode, Settings } from "@/lib/api";
import { AGENT_META } from "./agents";

const MODES: Mode[] = ["auto", "research", "plan", "execute"];

export function AgentPicker({ mode, onChange, settings }: { mode: Mode; onChange: (m: Mode) => void; settings: Settings | null }) {
  const enabled = (m: Mode) => m === "auto" || (settings?.enabled[m] ?? true);

  return (
    <div role="radiogroup" aria-label="Talk to" className="inline-flex rounded-full border border-line bg-sunken p-0.5">
      {MODES.map((m) => {
        const meta = AGENT_META[m];
        const active = mode === m;
        const on = enabled(m);
        return (
          <button
            key={m}
            role="radio"
            aria-checked={active}
            disabled={!on}
            title={on ? meta.blurb : `${meta.label} is switched off in Settings`}
            onClick={() => onChange(m)}
            className={[
              "flex items-center gap-1.5 rounded-full px-3 py-1 text-[13px] font-medium transition-colors",
              active ? `${meta.wash} ${meta.text} shadow-[inset_0_0_0_1px_currentColor]` : "text-muted hover:text-ink",
              on ? "" : "cursor-not-allowed line-through opacity-45 hover:text-muted",
            ].join(" ")}
          >
            {m !== "auto" && <span aria-hidden className={`size-1.5 rounded-full ${meta.bg}`} />}
            {meta.label}
          </button>
        );
      })}
    </div>
  );
}
