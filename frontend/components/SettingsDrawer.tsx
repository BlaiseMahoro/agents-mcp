"use client";

import { useEffect, useRef, useState } from "react";
import { api, ApiError, type Health, type Settings, SPECIALISTS } from "@/lib/api";
import { AGENT_META } from "./agents";

type Props = {
  open: boolean;
  settings: Settings | null;
  health: Health | null;
  onClose: () => void;
  onChange: (s: Settings) => void;
  onRecheck: () => void;
};

const ROWS = ["orchestrator", ...SPECIALISTS] as const;

export function SettingsDrawer({ open, settings, health, onClose, onChange, onRecheck }: Props) {
  const [models, setModels] = useState<Record<string, string[]>>({});
  const [error, setError] = useState("");
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    api.models().then(setModels).catch(() => {});
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open || !settings) return null;

  const save = async (patch: Parameters<typeof api.saveSettings>[0]) => {
    setError("");
    try {
      onChange(await api.saveSettings(patch));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  return (
    <div className="fixed inset-0 z-30 flex justify-end">
      <button aria-label="Close settings" className="absolute inset-0 bg-ink/20" onClick={onClose} />
      <aside role="dialog" aria-modal="true" aria-label="Settings" className="relative flex h-full w-full max-w-[440px] flex-col overflow-y-auto bg-surface shadow-xl">
        <header className="flex items-center justify-between border-b border-line px-5 py-4">
          <h2 className="text-[17px] font-semibold">Settings</h2>
          <button ref={closeRef} onClick={onClose} className="rounded-lg px-2.5 py-1 text-sm text-muted hover:bg-sunken hover:text-ink">
            Done
          </button>
        </header>

        {error && <p className="mx-5 mt-4 rounded-lg bg-sunken px-3 py-2 text-[13px] text-danger">{error}</p>}

        <section className="px-5 pt-5">
          <h3 className="text-[15px] font-semibold">Agents</h3>
          <p className="mt-0.5 text-[13px] text-muted">A switched-off agent can’t be picked, and Auto won’t call it. The MCP server picks up changes when it restarts.</p>
          <ul className="mt-3 space-y-3">
            {ROWS.map((name) => {
              const meta = AGENT_META[name];
              const cfg = settings.agents[name];
              const toggleable = name !== "orchestrator";
              const on = toggleable ? settings.enabled[name] : true;
              const options = models[cfg.provider] ?? [];
              return (
                <li key={name} className={`rounded-xl border border-line p-3 ${on ? "" : "opacity-60"}`}>
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className={`text-[14px] font-semibold ${meta.text}`}>{name === "orchestrator" ? "Auto (coordinator)" : meta.label}</p>
                      <p className="text-[12.5px] text-muted">{name === "orchestrator" ? "Routes Auto messages to the other agents" : meta.blurb}</p>
                    </div>
                    {toggleable && <Switch label={`${meta.label} agent`} checked={on} onChange={(v) => save({ enabled: { [name]: v } as Settings["enabled"] })} />}
                  </div>
                  <div className="mt-2.5 grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-2 text-[13px]">
                    <label htmlFor={`${name}-provider`} className="text-muted">
                      Provider
                    </label>
                    <select
                      id={`${name}-provider`}
                      value={cfg.provider}
                      onChange={(e) => {
                        const provider = e.target.value;
                        const first = models[provider]?.[0];
                        save({ agents: { [name]: { provider, ...(first ? { model: first } : {}) } } });
                      }}
                      className="rounded-md border border-line bg-surface px-2 py-1"
                    >
                      {settings.providers.map((p) => (
                        <option key={p}>{p}</option>
                      ))}
                    </select>
                    <label htmlFor={`${name}-model`} className="text-muted">
                      Model
                    </label>
                    <ModelInput key={cfg.model} id={`${name}-model`} value={cfg.model} options={options} onCommit={(model) => save({ agents: { [name]: { model } } })} />
                    {name === "research" && (
                      <>
                        <label htmlFor="research-search" className="text-muted">
                          Web search
                        </label>
                        <select
                          id="research-search"
                          value={cfg.search}
                          onChange={(e) => save({ agents: { research: { search: e.target.value } } })}
                          className="rounded-md border border-line bg-surface px-2 py-1"
                        >
                          <option value="searxng">SearXNG (works with any model)</option>
                          <option value="native">Built in (Claude only)</option>
                        </select>
                      </>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </section>

        <section className="px-5 pt-6">
          <div className="flex items-center justify-between gap-3 rounded-xl border border-line p-3">
            <div>
              <p className="text-[14px] font-semibold">Ask before running plans</p>
              <p className="text-[12.5px] text-muted">In Auto, plans wait for you to press Run plan.</p>
            </div>
            <Switch label="Ask before running plans" checked={settings.require_approval} onChange={(v) => save({ require_approval: v })} />
          </div>
        </section>

        <section className="px-5 py-6">
          <div className="flex items-center justify-between">
            <h3 className="text-[15px] font-semibold">Services</h3>
            <button onClick={onRecheck} className="rounded-lg px-2 py-1 text-[13px] text-muted hover:bg-sunken hover:text-ink">
              Check again
            </button>
          </div>
          {health ? (
            <ul className="mt-2 divide-y divide-line rounded-xl border border-line text-[13px]">
              <HealthRow name="Docker" check={health.docker} fix="Open Docker Desktop." />
              <HealthRow name="Sandbox image" check={health.sandbox_image} fix="Run `make sandbox`." />
              <HealthRow name="SearXNG search" check={health.searxng} fix="Run `docker compose up -d searxng`." />
              {Object.entries(health.providers).map(([p, c]) => (
                <HealthRow key={p} name={p} check={c} fix={p === "lmstudio" ? "Start the server in LM Studio (Developer tab) or run `lms server start`." : p === "ollama" ? "Run `ollama serve`." : ""} />
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-[13px] text-muted">Checking services…</p>
          )}
        </section>
      </aside>
    </div>
  );
}

function ModelInput({ id, value, options, onCommit }: { id: string; value: string; options: string[]; onCommit: (v: string) => void }) {
  const [v, setV] = useState(value);
  const commit = () => v.trim() && v !== value && onCommit(v.trim());
  return (
    <>
      <input
        id={id}
        list={`${id}-options`}
        value={v}
        onChange={(e) => setV(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === "Enter" && commit()}
        className="min-w-0 rounded-md border border-line bg-surface px-2 py-1 font-mono text-[12.5px]"
      />
      <datalist id={`${id}-options`}>
        {options.map((o) => (
          <option key={o} value={o} />
        ))}
      </datalist>
    </>
  );
}

function Switch({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={`relative h-6 w-10 shrink-0 rounded-full transition-colors ${checked ? "bg-execute" : "bg-line"}`}
    >
      <span className={`absolute top-0.5 left-0.5 size-5 rounded-full bg-surface shadow transition-transform ${checked ? "translate-x-4" : ""}`} />
    </button>
  );
}

function HealthRow({ name, check, fix }: { name: string; check: { ok: boolean; detail: string }; fix: string }) {
  return (
    <li className="flex items-start gap-2.5 px-3 py-2">
      <span aria-hidden className={`mt-1.5 size-2 shrink-0 rounded-full ${check.ok ? "bg-execute" : "bg-danger"}`} />
      <div className="min-w-0">
        <p className="font-medium">
          {name} <span className="sr-only">{check.ok ? "working" : "not working"}</span>
        </p>
        {!check.ok && (
          <p className="text-muted">
            {check.detail}
            {fix && <span className="block text-ink">{fix}</span>}
          </p>
        )}
      </div>
    </li>
  );
}
