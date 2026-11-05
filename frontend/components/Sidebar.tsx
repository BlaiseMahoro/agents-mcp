"use client";

import type { Conversation, Settings } from "@/lib/api";
import { SPECIALISTS } from "@/lib/api";
import { AGENT_META } from "./agents";

type Props = {
  conversations: Conversation[];
  activeId: string | null;
  settings: Settings | null;
  healthy: boolean | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onSettings: () => void;
};

export function Sidebar({ conversations, activeId, settings, healthy, onSelect, onNew, onDelete, onSettings }: Props) {
  return (
    <nav aria-label="Chats" className="flex h-full w-[264px] shrink-0 flex-col border-r border-line bg-surface">
      <div className="px-4 pt-4 pb-3">
        <p className="text-[17px] font-bold tracking-tight">Agents</p>
        <div className="mt-2 flex gap-1" aria-label="Agents switched on">
          {SPECIALISTS.map((a) => {
            const on = settings?.enabled[a] ?? true;
            return (
              <span
                key={a}
                title={`${AGENT_META[a].label} is ${on ? "on" : "off"}`}
                className={`h-1 flex-1 rounded-full ${on ? AGENT_META[a].bg : "bg-line"}`}
              />
            );
          })}
        </div>
      </div>

      <div className="px-3">
        <button onClick={onNew} className="w-full rounded-lg border border-line px-3 py-2 text-left text-[14px] font-medium hover:bg-sunken">
          New chat
        </button>
      </div>

      <ul className="mt-3 flex-1 overflow-y-auto px-2 pb-2">
        {conversations.length === 0 && <li className="px-2 py-1 text-[13px] text-muted">Your chats will show up here.</li>}
        {conversations.map((c) => (
          <li key={c.id} className="group relative">
            <button
              onClick={() => onSelect(c.id)}
              aria-current={c.id === activeId ? "page" : undefined}
              className={`w-full truncate rounded-lg px-2.5 py-1.5 pr-8 text-left text-[14px] ${
                c.id === activeId ? "bg-sunken font-medium text-ink" : "text-muted hover:bg-sunken hover:text-ink"
              }`}
            >
              {c.title}
            </button>
            <button
              onClick={() => onDelete(c.id)}
              aria-label={`Delete chat ${c.title}`}
              className="absolute top-1/2 right-1.5 -translate-y-1/2 rounded px-1.5 text-muted opacity-0 group-hover:opacity-100 hover:text-danger focus-visible:opacity-100"
            >
              ×
            </button>
          </li>
        ))}
      </ul>

      <div className="border-t border-line p-3">
        <button onClick={onSettings} className="flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-[14px] hover:bg-sunken">
          Settings
          <span className="flex items-center gap-1.5 text-[12px] text-muted">
            <span
              aria-hidden
              className={`size-2 rounded-full ${healthy === null ? "bg-line" : healthy ? "bg-execute" : "bg-danger"}`}
            />
            {healthy === null ? "Checking" : healthy ? "All services up" : "Needs attention"}
          </span>
        </button>
      </div>
    </nav>
  );
}
