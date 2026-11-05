"use client";

import { useEffect, useState } from "react";
import { api, type Message, type Plan, type ResearchReport } from "@/lib/api";
import { buildLanes, type Block, type Lane } from "@/lib/turn";
import { useActions } from "./actions";
import { AGENT_META } from "./agents";
import { Markdown } from "./Markdown";
import { PlanCard } from "./PlanCard";
import { RunCard } from "./RunCard";

export function UserMessage({ message }: { message: Message }) {
  const meta = message.mode !== "auto" && message.mode in AGENT_META ? AGENT_META[message.mode as keyof typeof AGENT_META] : null;
  return (
    <div className="flex flex-col items-end gap-1">
      {meta && <span className={`text-[12px] font-medium ${meta.text}`}>To {meta.label}</span>}
      <div className="max-w-[85%] rounded-2xl rounded-tr-md bg-surface px-4 py-2.5 whitespace-pre-wrap shadow-[inset_0_0_0_1px_var(--line)]">
        {message.content}
      </div>
    </div>
  );
}

export function AssistantMessage({ message }: { message: Message }) {
  const lanes = buildLanes(message.events);
  if (lanes.length === 0) {
    return message.pending ? <Working label="Starting" /> : message.content ? <Markdown text={message.content} /> : null;
  }
  return (
    <div className="flex flex-col gap-4">
      {lanes.map((lane, i) => (
        <LaneView key={i} lane={lane} live={Boolean(message.pending) && i === lanes.length - 1} />
      ))}
    </div>
  );
}

function LaneView({ lane, live }: { lane: Lane; live: boolean }) {
  const meta = AGENT_META[lane.agent];
  // The coordinator's own words read as the main voice; specialists get a coloured lane.
  const plain = lane.agent === "orchestrator" || lane.agent === "system";
  return (
    <div className={plain ? "" : `border-l-[3px] pl-4 ${meta.border}`}>
      {!plain && (
        <p className={`mb-1.5 flex items-center gap-2 text-[13px] font-semibold ${meta.text}`}>
          {meta.label}
          {live && <span aria-hidden className={`size-1.5 rounded-full pulse ${meta.bg}`} />}
        </p>
      )}
      <div className="flex flex-col gap-2.5">
        {lane.blocks.map((b, i) => (
          <BlockView key={i} block={b} />
        ))}
      </div>
    </div>
  );
}

function BlockView({ block }: { block: Block }) {
  switch (block.kind) {
    case "text":
      return <Markdown text={block.text} />;
    case "thinking":
      return (
        <details className="text-[13px] text-muted">
          <summary className="cursor-pointer select-none hover:text-ink">Reasoning</summary>
          <p className="mt-1 max-w-[68ch] whitespace-pre-wrap">{block.text}</p>
        </details>
      );
    case "tool":
      return <ToolLine block={block} />;
    case "research":
      return <ResearchCard report={block.report} />;
    case "plan":
      return <PlanCard plan={block.plan} />;
    case "approval":
      return <Approval planId={block.planId} />;
    case "run":
      return <RunCard run={block} />;
    case "error":
      return (
        <p role="alert" className="rounded-lg border border-danger/40 bg-surface px-3 py-2 text-[14px] text-danger">
          {block.message}
        </p>
      );
  }
}

function ToolLine({ block }: { block: Extract<Block, { kind: "tool" }> }) {
  const q = block.input?.query ?? block.input?.url ?? "";
  const verb =
    block.name === "web_search" ? "Searched" : block.name === "fetch_url" || block.name === "web_fetch" ? "Read" : `Used ${block.name}`;
  const shown = block.name === "fetch_url" || block.name === "web_fetch" ? hostOf(q) : q;
  return (
    <details className="text-[13px] text-muted">
      <summary className={`select-none ${block.results?.length ? "cursor-pointer hover:text-ink" : "list-none"}`}>
        {verb} {shown && <span className="text-ink">“{shown}”</span>}
        {block.results && <span> with {block.results.length} results</span>}
        {block.error && <span className="text-danger"> (failed)</span>}
      </summary>
      {block.results && (
        <ul className="mt-1 ml-4 space-y-0.5">
          {block.results.map((r) => (
            <li key={r.url} className="truncate">
              <a href={r.url} target="_blank" rel="noreferrer" className="hover:text-research hover:underline">
                {r.title || r.url}
              </a>
              <span className="ml-1.5 text-muted/70">{hostOf(r.url)}</span>
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}

function ResearchCard({ report }: { report: ResearchReport }) {
  const findings = report.key_findings ?? [];
  const sources = report.sources ?? [];
  const open = report.open_questions ?? [];
  if (!findings.length && !sources.length) return null;
  return (
    <section aria-label="Research summary" className="rounded-xl border border-line bg-surface">
      {findings.length > 0 && (
        <div className="border-b border-line bg-research-wash px-4 py-3">
          <h3 className="text-[14px] font-semibold">Key findings</h3>
          <ul className="mt-1.5 list-disc space-y-1 pl-5 text-[14px]">
            {findings.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </div>
      )}
      {sources.length > 0 && (
        <div className="px-4 py-3">
          <h3 className="text-[14px] font-semibold">Sources</h3>
          <ol className="mt-1.5 space-y-1 text-[14px]">
            {sources.map((s, i) => (
              <li key={s.url} className="flex gap-2">
                <span className="w-5 shrink-0 text-right tabular-nums text-muted">{i + 1}</span>
                <a href={s.url} target="_blank" rel="noreferrer" className="min-w-0 truncate text-research hover:underline">
                  {s.title || s.url}
                </a>
                <span className="shrink-0 text-[13px] text-muted">{hostOf(s.url)}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
      {open.length > 0 && (
        <details className="border-t border-line px-4 py-2.5 text-[13px] text-muted">
          <summary className="cursor-pointer select-none hover:text-ink">Still open ({open.length})</summary>
          <ul className="mt-1 list-disc pl-5">
            {open.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

function Approval({ planId }: { planId: string }) {
  const { version, runPlan, streaming, settings } = useActions();
  const [plan, setPlan] = useState<Plan | null>(null);
  useEffect(() => {
    api.plan(planId).then(setPlan).catch(() => {});
  }, [planId, version]);
  if (!plan) return null;
  const waiting = plan.status === "draft" || plan.status === "approved";
  const canRun = (settings?.enabled.execute ?? true) && !streaming;
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-execute bg-execute-wash px-4 py-3">
      <p className="min-w-0 flex-1 text-[14px]">
        {waiting ? (
          <>
            Ready to run <span className="font-semibold">{plan.goal}</span> ({plan.steps.length} steps). Check the steps above first.
          </>
        ) : (
          <>This plan has already been run. See the results below.</>
        )}
      </p>
      {waiting && (
        <div className="flex gap-2">
          <button onClick={() => runPlan(plan.id, false)} disabled={!canRun} className="rounded-lg bg-execute px-3.5 py-1.5 text-sm font-semibold text-white disabled:opacity-40">
            Run plan
          </button>
          <button onClick={() => runPlan(plan.id, true)} disabled={!canRun} className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm hover:bg-sunken disabled:opacity-40">
            Preview run
          </button>
        </div>
      )}
    </div>
  );
}

export function Working({ label }: { label: string }) {
  return (
    <p className="flex items-center gap-2 text-[14px] text-muted">
      <span aria-hidden className="size-1.5 rounded-full bg-muted pulse" />
      {label}
    </p>
  );
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}
