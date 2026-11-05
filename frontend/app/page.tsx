"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ActionsContext, type ChatActions } from "@/components/actions";
import { AGENT_META } from "@/components/agents";
import { Composer } from "@/components/Composer";
import { SettingsDrawer } from "@/components/SettingsDrawer";
import { Sidebar } from "@/components/Sidebar";
import { AssistantMessage, UserMessage } from "@/components/Turn";
import { api, ApiError, type AgentEvent, type Conversation, type Health, type Message, type Mode, type Settings, SPECIALISTS, streamEvents } from "@/lib/api";

export default function Home() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [pickedMode, setMode] = useState<Mode>("auto");
  const [settings, setSettings] = useState<Settings | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [chatsOpen, setChatsOpen] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [version, setVersion] = useState(0);
  const [banner, setBanner] = useState("");
  const abort = useRef<AbortController | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  const refreshConversations = useCallback(() => api.conversations().then(setConversations).catch((e) => setBanner(e.message)), []);
  const checkHealth = useCallback(() => {
    setHealth(null);
    api.health().then(setHealth).catch(() => {});
  }, []);

  useEffect(() => {
    api.conversations().then(setConversations).catch((e) => setBanner(e.message));
    api.settings().then(setSettings).catch((e) => setBanner(e.message));
    api.health().then(setHealth).catch(() => {});
  }, []);

  // Fall back to Auto while the picked agent is switched off.
  const mode: Mode = settings && pickedMode !== "auto" && !settings.enabled[pickedMode] ? "auto" : pickedMode;

  useEffect(() => {
    if (stick.current) scroller.current?.scrollTo({ top: scroller.current.scrollHeight });
  }, [messages]);

  const openConversation = useCallback(async (id: string) => {
    abort.current?.abort();
    setActiveId(id);
    setBanner("");
    try {
      const conv = await api.conversation(id);
      setMessages(conv.messages);
      stick.current = true;
    } catch (e) {
      setBanner((e as Error).message);
    }
  }, []);

  /** Append a pending assistant message and feed it events from an SSE request. */
  const stream = useCallback(
    async (path: string, body: unknown, userMessage?: Message) => {
      const pendingId = `pending-${Date.now()}`;
      const pending: Message = { id: pendingId, role: "assistant", mode: "auto", content: "", events: [], pending: true };
      setMessages((m) => [...m, ...(userMessage ? [userMessage] : []), pending]);
      setStreaming(true);
      stick.current = true;
      const ctrl = new AbortController();
      abort.current = ctrl;
      const onEvent = (ev: AgentEvent) =>
        setMessages((ms) => ms.map((m) => (m.id === pendingId ? { ...m, events: [...m.events, ev] } : m)));
      try {
        await streamEvents(path, body, onEvent, ctrl.signal);
      } catch (e) {
        onEvent({ type: "error", agent: null, data: { message: e instanceof ApiError ? e.message : String(e) } });
      } finally {
        setMessages((ms) => ms.map((m) => (m.id === pendingId ? { ...m, pending: false } : m)));
        setStreaming(false);
        setVersion((v) => v + 1);
        refreshConversations();
      }
    },
    [refreshConversations],
  );

  const send = async (text: string) => {
    let id = activeId;
    if (!id) {
      try {
        const conv = await api.createConversation();
        id = conv.id;
        setActiveId(id);
        setMessages([]);
      } catch (e) {
        setBanner((e as Error).message);
        return;
      }
    }
    const user: Message = { id: `local-${Date.now()}`, role: "user", mode, content: text, events: [] };
    await stream(`/api/conversations/${id}/messages`, { content: text, mode }, user);
  };

  const actions: ChatActions = useMemo(
    () => ({
      settings,
      streaming,
      version,
      runPlan: (planId, dryRun) => stream(`/api/plans/${planId}/execute?dry_run=${dryRun}`, undefined),
      cancelRun: (runId) => {
        api.cancelRun(runId).catch(() => {});
      },
    }),
    [settings, streaming, version, stream],
  );

  const healthy = health
    ? health.docker.ok && health.sandbox_image.ok && health.searxng.ok && Object.values(health.providers).every((p) => p.ok)
    : null;

  return (
    <ActionsContext.Provider value={actions}>
      <div className="flex h-dvh overflow-hidden">
        {/* Desktop: always visible. Phone: slides over the chat from the Chats button. */}
        <div className={chatsOpen ? "fixed inset-0 z-20 flex md:static md:block" : "hidden md:block"}>
          <Sidebar
            conversations={conversations}
            activeId={activeId}
            settings={settings}
            healthy={healthy}
            onSelect={(id) => {
              setChatsOpen(false);
              openConversation(id);
            }}
            onNew={() => {
              abort.current?.abort();
              setChatsOpen(false);
              setActiveId(null);
              setMessages([]);
            }}
            onDelete={async (id) => {
              await api.deleteConversation(id).catch(() => {});
              if (id === activeId) {
                setActiveId(null);
                setMessages([]);
              }
              refreshConversations();
            }}
            onSettings={() => {
              setChatsOpen(false);
              setSettingsOpen(true);
            }}
          />
          {chatsOpen && <button aria-label="Close chats" className="flex-1 bg-ink/20 md:hidden" onClick={() => setChatsOpen(false)} />}
        </div>

        <main className="flex min-w-0 flex-1 flex-col">
          <header className="flex items-center justify-between border-b border-line px-4 py-2.5 md:hidden">
            <button onClick={() => setChatsOpen(true)} className="rounded-lg px-2.5 py-1 text-sm hover:bg-sunken">
              Chats
            </button>
            <p className="font-bold">Agents</p>
            <button onClick={() => setSettingsOpen(true)} className="rounded-lg px-2.5 py-1 text-sm hover:bg-sunken">
              Settings
            </button>
          </header>

          {banner && (
            <p role="alert" className="border-b border-line bg-surface px-4 py-2 text-[14px] text-danger">
              {banner}
            </p>
          )}

          <div
            ref={scroller}
            onScroll={(e) => {
              const el = e.currentTarget;
              stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
            }}
            className="flex-1 overflow-y-auto px-4"
          >
            <div className="mx-auto flex max-w-[760px] flex-col gap-6 py-8">
              {messages.length === 0 ? (
                <EmptyState settings={settings} onPick={setMode} />
              ) : (
                messages.map((m) => (m.role === "user" ? <UserMessage key={m.id} message={m} /> : <AssistantMessage key={m.id} message={m} />))
              )}
            </div>
          </div>

          <Composer mode={mode} onMode={setMode} settings={settings} streaming={streaming} onSend={send} onStop={() => abort.current?.abort()} />
        </main>
      </div>

      <SettingsDrawer
        open={settingsOpen}
        settings={settings}
        health={health}
        onClose={() => setSettingsOpen(false)}
        onChange={setSettings}
        onRecheck={checkHealth}
      />
    </ActionsContext.Provider>
  );
}

function EmptyState({ settings, onPick }: { settings: Settings | null; onPick: (m: Mode) => void }) {
  return (
    <div className="pt-[12vh]">
      <h1 className="max-w-[22ch] text-[28px] leading-tight font-bold tracking-tight">Look something up, make a plan, then run it.</h1>
      <p className="mt-2 max-w-[60ch] text-muted">
        Auto decides which agent to use. To talk to one directly, pick it below the chat. Plans run in a Docker sandbox, and you can review them first.
      </p>
      <ul className="mt-8 grid gap-3 sm:grid-cols-3">
        {SPECIALISTS.map((a) => {
          const meta = AGENT_META[a];
          const on = settings?.enabled[a] ?? true;
          const model = settings?.agents[a]?.model;
          return (
            <li key={a}>
              <button
                onClick={() => onPick(a)}
                disabled={!on}
                className={`flex h-full w-full flex-col items-start rounded-xl border-t-[3px] bg-surface p-3.5 text-left shadow-[inset_0_0_0_1px_var(--line)] hover:bg-sunken disabled:opacity-50 ${meta.border}`}
              >
                <span className={`text-[14px] font-semibold ${meta.text}`}>{meta.label}</span>
                <span className="mt-1 block text-[13px] text-muted">{meta.blurb}</span>
                <span className="mt-auto block w-full truncate pt-2 font-mono text-[11.5px] text-muted">{on ? model : "Switched off"}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
