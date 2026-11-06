"use client";

import type { Mode, Settings } from "@/lib/api";
import { AGENT_META } from "./agents";

const MODES: Mode[] = ["auto", "research", "plan", "execute"];

export function AgentPicker({ mode, onChange, settings }: { mode: Mode; onChange: (m: Mode) => void; settings: Settings | null }) {
  const enabled = (m: Mode) => m === "auto" || (settings?.enabled[m] ?? true);

  return (
    <div role="radiogroup" aria-label="Talk to" className="inline-flex flex-wrap rounded-md border border-line bg-surface p-0.5">
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
              "flex items-center gap-1.5 rounded px-2.5 py-1 text-[14px] transition-colors",
              active ? `${meta.wash} ${meta.text} shadow-[inset_0_0_0_1px_currentColor]` : "text-muted hover:text-ink",
              on ? "" : "cursor-not-allowed line-through opacity-45 hover:text-muted",
            ].join(" ")}
          >
            <span aria-hidden className={active ? "" : meta.text}>
              {meta.sigil}
            </span>
            {meta.label}
          </button>
        );
      })}
    </div>
  );
}
