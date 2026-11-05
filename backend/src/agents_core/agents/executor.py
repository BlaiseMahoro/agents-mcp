"""Execute agent: runs a Plan's steps in dependency order inside a sandbox.

Running steps is deterministic code; only `llm_task` steps call a model.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

from agents_core.config import SandboxConfig
from agents_core.sandbox.docker_runner import ExecChunk, ExecDone, Sandbox
from agents_core.schemas import (
    AgentEvent,
    ExecutionReport,
    LLMTaskStep,
    Plan,
    ReadFileStep,
    ShellStep,
    StepResult,
    WriteFileStep,
    topo_order,
    utcnow,
)

LLMFn = Callable[[str], Awaitable[str]]
MAX_OUTPUT_CHARS = 20_000

# run_id -> cancel flag, so the API can cancel a running plan
_cancel_flags: dict[str, asyncio.Event] = {}


def request_cancel(run_id: str) -> bool:
    flag = _cancel_flags.get(run_id)
    if flag:
        flag.set()
    return flag is not None


class PlanRejected(ValueError):
    pass


def resolve_in_workspace(workspace: Path, rel: str) -> Path:
    """Resolve a step path; refuse anything that escapes the workspace."""
    root = workspace.resolve()
    target = (root / rel.lstrip("/")).resolve()
    if target != root and root not in target.parents:
        raise PlanRejected(f"path {rel!r} escapes the workspace")
    return target


def check_plan(plan: Plan, cfg: SandboxConfig) -> None:
    disallowed = sorted({s.type for s in plan.steps} - set(cfg.allowed_step_types))
    if disallowed:
        raise PlanRejected(f"step types not allowed by config: {disallowed}")


async def execute_plan(
    plan: Plan,
    sandbox: Sandbox,
    cfg: SandboxConfig,
    llm: LLMFn | None = None,
    dry_run: bool = False,
    report: ExecutionReport | None = None,
) -> AsyncIterator[AgentEvent | ExecutionReport]:
    """Yield progress events; the last item is the final ExecutionReport."""
    check_plan(plan, cfg)
    ordered = topo_order(plan.steps)
    report = report or ExecutionReport(plan_id=plan.id, dry_run=dry_run)
    report.steps = [StepResult(step_id=s.id) for s in ordered]
    results = {r.step_id: r for r in report.steps}
    cancel = _cancel_flags.setdefault(report.id, asyncio.Event())

    yield AgentEvent(type="run_start", agent="execute", data={"run_id": report.id, "plan_id": plan.id, "dry_run": dry_run, "steps": [s.id for s in ordered]})

    started = False
    try:
        if not dry_run:
            await sandbox.start()
            started = True
        halted = False
        for step in ordered:
            res = results[step.id]
            blocked = [d for d in [*step.depends_on, *getattr(step, "inputs_from", [])] if results[d].status != "succeeded"]
            if cancel.is_set():
                res.status = "cancelled"
            elif halted or (blocked and not dry_run):
                res.status = "skipped"
                res.error = "skipped: an earlier step failed" if halted else f"skipped: dependencies not met {blocked}"
            if res.status != "pending":
                yield AgentEvent(type="step_end", agent="execute", data=res.model_dump())
                continue

            res.status = "running"
            yield AgentEvent(type="step_start", agent="execute", data={"step_id": step.id, "type": step.type, "description": step.description})
            t0 = time.monotonic()
            try:
                if dry_run:
                    res.output = _describe(step)
                    res.status = "succeeded"
                else:
                    async for ev in _run_step(step, sandbox, cfg, llm, results, res, cancel):
                        yield ev
            except PlanRejected as e:
                res.status, res.error = "failed", str(e)
            except Exception as e:  # noqa: BLE001 - one step failing must not kill the run
                res.status, res.error = "failed", f"{type(e).__name__}: {e}"
            res.duration_s = round(time.monotonic() - t0, 2)
            res.output = res.output[-MAX_OUTPUT_CHARS:]
            yield AgentEvent(type="step_end", agent="execute", data=res.model_dump())
            if res.status == "failed" and step.on_failure == "stop":
                halted = True

        statuses = {r.status for r in report.steps}
        if cancel.is_set():
            report.status = "cancelled"
        elif "failed" in statuses or "skipped" in statuses:
            report.status = "failed"
        else:
            report.status = "succeeded"
    finally:
        if started:
            await sandbox.stop()
        _cancel_flags.pop(report.id, None)
        report.finished_at = utcnow()

    yield AgentEvent(type="run_end", agent="execute", data={"run_id": report.id, "status": report.status})
    yield report


def _describe(step) -> str:
    match step:
        case ShellStep():
            return f"$ {step.command}"
        case WriteFileStep():
            return f"write {step.path} ({len(step.content)} chars)"
        case ReadFileStep():
            return f"read {step.path}"
        case LLMTaskStep():
            return f"llm: {step.prompt[:200]}"
    return step.type


async def _run_step(step, sandbox: Sandbox, cfg: SandboxConfig, llm: LLMFn | None, results: dict[str, StepResult], res: StepResult, cancel: asyncio.Event) -> AsyncIterator[AgentEvent]:
    match step:
        case ShellStep():
            out: list[str] = []
            async for item in sandbox.exec(step.command, cfg.step_timeout_s):
                if cancel.is_set():
                    raise RuntimeError("cancelled")
                if isinstance(item, ExecChunk):
                    out.append(item.text)
                    yield AgentEvent(type="step_output", agent="execute", data={"step_id": step.id, "stream": item.stream, "text": item.text})
                elif isinstance(item, ExecDone):
                    res.exit_code = item.exit_code
                    res.output = "".join(out)
                    if item.timed_out:
                        res.status, res.error = "failed", f"timed out after {cfg.step_timeout_s}s"
                    elif item.exit_code != 0:
                        res.status, res.error = "failed", f"exit code {item.exit_code}"
                    else:
                        res.status = "succeeded"
        case WriteFileStep():
            target = resolve_in_workspace(sandbox.workspace, step.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(step.content)
            res.output, res.status = f"wrote {step.path} ({len(step.content)} chars)", "succeeded"
        case ReadFileStep():
            target = resolve_in_workspace(sandbox.workspace, step.path)
            if not target.is_file():
                res.status, res.error = "failed", f"no such file: {step.path}"
            else:
                res.output, res.status = target.read_text(errors="replace"), "succeeded"
        case LLMTaskStep():
            if llm is None:
                raise PlanRejected("llm_task steps need a model, but none is configured for the execute agent")
            context = "\n\n".join(f"### Output of step {sid}\n{results[sid].output}" for sid in step.inputs_from)
            prompt = f"{step.prompt}\n\n{context}" if context else step.prompt
            res.output = await llm(prompt)
            res.status = "succeeded"
            yield AgentEvent(type="step_output", agent="execute", data={"step_id": step.id, "stream": "stdout", "text": res.output})
