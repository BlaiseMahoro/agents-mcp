"use client";

import { useEffect, useRef, useState } from "react";
import type { Mode, Settings } from "@/lib/api";
import { AgentPicker } from "./AgentPicker";
import { AGENT_META, PLACEHOLDER } from "./agents";

type Props = {
  mode: Mode;
  onMode: (m: Mode) => void;
  settings: Settings | null;
  streaming: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
};

export function Composer({ mode, onMode, settings, streaming, onSend, onStop }: Props) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }, [text]);

  useEffect(() => ref.current?.focus(), [mode]);

  const send = () => {
    const t = text.trim();
    if (!t || streaming) return;
    onSend(t);
    setText("");
  };

  const meta = AGENT_META[mode];

  return (
    <div className="border-t border-line bg-fog/95 px-4 pb-4 pt-3 backdrop-blur">
      <div className="mx-auto max-w-[760px]">
        <div className="mb-2 flex items-center justify-between gap-3">
          <AgentPicker mode={mode} onChange={onMode} settings={settings} />
          <span className="hidden text-[13px] text-muted sm:block">{meta.blurb}</span>
        </div>
        <div className={`flex items-end gap-2 rounded-2xl border bg-surface p-2 transition-colors focus-within:border-current ${meta.text} border-line`}>
          <label htmlFor="composer" className="sr-only">
            Message
          </label>
          <textarea
            id="composer"
            ref={ref}
            rows={1}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                send();
              }
            }}
            placeholder={PLACEHOLDER[mode]}
            className="min-h-[40px] flex-1 resize-none bg-transparent px-2 py-2 text-[15px] text-ink placeholder:text-muted focus:outline-none focus-visible:outline-none"
          />
          {streaming ? (
            <button onClick={onStop} className="rounded-xl border border-line px-4 py-2 text-sm font-medium text-ink hover:bg-sunken">
              Stop
            </button>
          ) : (
            <button
              onClick={send}
              disabled={!text.trim()}
              className={`rounded-xl px-4 py-2 text-sm font-semibold disabled:opacity-40 ${mode === "auto" ? "bg-ink text-surface" : `${meta.bg} text-white`}`}
            >
              Send
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
