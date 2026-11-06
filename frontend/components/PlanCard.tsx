"use client";

import { useEffect, useState } from "react";
import { api, ApiError, type Plan, type Step } from "@/lib/api";
import { useActions } from "./actions";

const STATUS_LABEL: Record<Plan["status"], string> = {
  draft: "Not cast yet",
  approved: "Approved",
  running: "Casting",
  succeeded: "Cast",
  failed: "Cast failed",
  cancelled: "Cast cancelled",
};

const TYPE_LABEL: Record<Step["type"], string> = {
  shell: "Command",
  write_file: "Write file",
  read_file: "Read file",
  llm_task: "Model task",
};

function stepBody(s: Step): { field: keyof Step; value: string } {
  switch (s.type) {
    case "shell":
      return { field: "command", value: s.command ?? "" };
    case "write_file":
      return { field: "content", value: s.content ?? "" };
    case "read_file":
      return { field: "path", value: s.path ?? "" };
    case "llm_task":
      return { field: "prompt", value: s.prompt ?? "" };
  }
}

export function PlanCard({ plan: initial }: { plan: Plan }) {
  const { runPlan, settings, streaming, version } = useActions();
  const [plan, setPlan] = useState<Plan>(initial);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Step[]>(initial.steps);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.plan(initial.id).then(setPlan).catch(() => {});
  }, [initial.id, version]);

  const executeOn = settings?.enabled.execute ?? true;
  const canRun = executeOn && !streaming && plan.status !== "running";

  const save = async () => {
    setSaving(true);
    setError("");
    try {
      const updated = await api.savePlan(plan.id, { steps: draft });
      setPlan(updated);
      setEditing(false);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const updateStep = (i: number, patch: Partial<Step>) => setDraft((d) => d.map((s, j) => (j === i ? { ...s, ...patch } : s)));

  return (
    <section
      aria-label={`Spell: ${plan.goal}`}
      // a manuscript frame: brass rule, a gap, a second hairline
      className="rounded-sm border border-research/70 bg-surface p-1"
    >
      <div className="border border-research/30">
      <header className="flex items-start justify-between gap-4 px-5 pt-4 pb-2">
        <div className="min-w-0 flex-1">
          <h3 className="max-w-[48ch] font-display text-[20px] leading-snug">{plan.goal}</h3>
          <p className="mt-0.5 text-[14px] text-muted">A spell of {plan.steps.length} steps</p>
        </div>
        <StatusPill status={plan.status} />
      </header>

      <div className="px-5 pb-3">
        <p className="dropcap max-w-[66ch] text-[15px]">{plan.summary}</p>
        {plan.assumptions.length > 0 && (
          <details className="mt-2 text-[14px] text-muted">
            <summary className="cursor-pointer select-none hover:text-ink">Assumptions ({plan.assumptions.length})</summary>
            <ul className="mt-1 list-disc pl-5">
              {plan.assumptions.map((a, i) => (
                <li key={i}>{a}</li>
              ))}
            </ul>
          </details>
        )}
      </div>

      <ol className="border-t border-line">
        {(editing ? draft : plan.steps).map((s, i) => {
          const body = stepBody(s);
          return (
            <li key={s.id} className="grid grid-cols-[2.5rem_1fr] gap-x-2 border-b border-line px-5 py-3 last:border-b-0">
              {/* rubric: the step number in cinnabar, as in a manuscript's instructions */}
              <span className="font-display text-[26px] leading-none text-plan">{i + 1}</span>
              <div className="min-w-0">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <span className="text-[13px] text-muted">{TYPE_LABEL[s.type]}</span>
                  {s.type === "write_file" && <span className="font-mono text-[12px] text-muted">{s.path}</span>}
                  {s.depends_on.length > 0 && <span className="text-[13px] text-muted">after {s.depends_on.join(", ")}</span>}
                  {s.on_failure === "continue" && <span className="text-[13px] text-muted">optional</span>}
                </div>
                {editing ? (
                  <>
                    <input
                      aria-label={`Step ${i + 1} description`}
                      value={s.description}
                      onChange={(e) => updateStep(i, { description: e.target.value })}
                      className="mt-1 w-full rounded-md border border-line bg-surface px-2 py-1 text-[14px]"
                    />
                    <textarea
                      aria-label={`Step ${i + 1} ${body.field}`}
                      value={body.value}
                      onChange={(e) => updateStep(i, { [body.field]: e.target.value })}
                      rows={Math.min(10, Math.max(1, body.value.split("\n").length))}
                      className="mt-1.5 w-full rounded-md border border-line bg-console px-2 py-1.5 font-mono text-[12.5px] text-console-ink"
                    />
                  </>
                ) : (
                  <>
                    <p className="text-[15px]">{s.description}</p>
                    {s.type !== "read_file" && body.value && (
                      <pre className="mt-1.5 max-h-48 overflow-auto rounded-md bg-console px-2.5 py-1.5 font-mono text-[12.5px] text-console-ink whitespace-pre-wrap">
                        {s.type === "shell" ? `$ ${body.value}` : body.value}
                      </pre>
                    )}
                  </>
                )}
              </div>
            </li>
          );
        })}
      </ol>

      {error && <p className="border-t border-line bg-sunken px-5 py-2 text-[14px] whitespace-pre-wrap text-danger">{error}</p>}

      <footer className="flex flex-wrap items-center gap-2 border-t border-line px-5 py-3">
        {editing ? (
          <>
            <button onClick={save} disabled={saving} className="rounded-md bg-plan px-3.5 py-1.5 text-[15px] font-bold text-fog disabled:opacity-50">
              {saving ? "Saving…" : "Save steps"}
            </button>
            <button
              onClick={() => {
                setEditing(false);
                setDraft(plan.steps);
                setError("");
              }}
              className="rounded-md px-3 py-1.5 text-[15px] text-muted hover:text-ink"
            >
              Discard edits
            </button>
          </>
        ) : (
          <>
            <button
              onClick={() => runPlan(plan.id, false)}
              disabled={!canRun}
              className="rounded-md bg-execute px-3.5 py-1.5 text-[15px] font-bold text-fog disabled:opacity-40"
            >
              {plan.status === "draft" || plan.status === "approved" ? "Cast spell" : "Cast again"}
            </button>
            <button onClick={() => runPlan(plan.id, true)} disabled={!canRun} className="rounded-md border border-line px-3 py-1.5 text-[15px] hover:bg-sunken disabled:opacity-40">
              Preview
            </button>
            <button
              onClick={() => {
                setDraft(plan.steps);
                setEditing(true);
              }}
              disabled={plan.status === "running"}
              className="rounded-md px-3 py-1.5 text-[15px] text-muted hover:text-ink disabled:opacity-40"
            >
              Edit steps
            </button>
            {!executeOn && <span className="text-[14px] text-muted">The Conjurer is switched off, so this spell can&rsquo;t be cast.</span>}
          </>
        )}
      </footer>
      </div>
    </section>
  );
}

function StatusPill({ status }: { status: Plan["status"] }) {
  const tone =
    status === "succeeded" ? "text-execute" : status === "failed" ? "text-danger" : status === "running" ? "text-plan" : "text-muted";
  return (
    <span className={`flex shrink-0 items-center gap-1.5 rounded-sm border border-current px-2 py-0.5 text-[13px] ${tone}`}>
      <span aria-hidden className={`size-1.5 rounded-full bg-current ${status === "running" ? "pulse" : ""}`} />
      {STATUS_LABEL[status]}
    </span>
  );
}
