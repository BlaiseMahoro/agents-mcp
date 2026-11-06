"use client";

import type { Block, StepState } from "@/lib/turn";
import { useActions } from "./actions";

type Run = Extract<Block, { kind: "run" }>;

const DOT: Record<string, string> = {
  pending: "border border-muted",
  running: "bg-plan pulse",
  succeeded: "bg-execute",
  failed: "bg-danger",
  skipped: "border border-dashed border-muted",
  cancelled: "bg-muted",
};

const RUN_LABEL: Record<string, string> = {
  running: "Casting",
  succeeded: "Cast complete",
  failed: "Cast failed",
  cancelled: "Cast cancelled",
};

export function RunCard({ run }: { run: Run }) {
  const { cancelRun } = useActions();
  const steps = run.order.map((id) => run.steps[id]).filter(Boolean);
  const done = steps.filter((s) => s.status === "succeeded").length;

  return (
    <section aria-label="Spell casting" className="overflow-hidden rounded-sm border border-line bg-surface">
      <header className="flex items-center justify-between gap-2 border-b border-line px-5 py-3">
        <p>
          <span className="font-display text-[19px] text-execute">{run.dryRun ? "Preview" : RUN_LABEL[run.status] ?? run.status}</span>
          <span className="ml-2 text-[15px] text-muted">
            {done} of {steps.length} steps done
          </span>
        </p>
        {run.status === "running" && (
          <button onClick={() => cancelRun(run.runId)} className="rounded-md border border-line px-3 py-1 text-[14px] hover:bg-sunken">
            Cancel cast
          </button>
        )}
      </header>
      <ul>
        {steps.map((s) => (
          <StepRow key={s.id} step={s} />
        ))}
      </ul>
    </section>
  );
}

function StepRow({ step }: { step: StepState }) {
  const hasOutput = Boolean(step.output || step.error);
  return (
    <li className="border-b border-line last:border-b-0">
      <details open={step.status === "running" || step.status === "failed"} className="group">
        <summary className={`flex items-center gap-3 px-5 py-2 text-[15px] ${hasOutput ? "cursor-pointer hover:bg-sunken" : "list-none"}`}>
          <span aria-hidden className={`size-2.5 shrink-0 rounded-full ${DOT[step.status] ?? DOT.pending}`} />
          <span className="sr-only">{step.status}</span>
          <span className="font-mono text-[12px] text-muted">{step.id}</span>
          <span className="min-w-0 flex-1 truncate">{step.description ?? ""}</span>
          {step.duration_s ? <span className="text-[12px] tabular-nums text-muted">{step.duration_s}s</span> : null}
        </summary>
        {hasOutput && (
          <div className="px-5 pb-3">
            {step.error && <p className="mb-1 text-[14px] text-danger">{step.error}</p>}
            {step.output && (
              <pre className="max-h-72 overflow-auto rounded-md bg-console px-3 py-2 font-mono text-[12.5px] leading-relaxed whitespace-pre-wrap text-console-ink">
                {step.output}
              </pre>
            )}
          </div>
        )}
      </details>
    </li>
  );
}
