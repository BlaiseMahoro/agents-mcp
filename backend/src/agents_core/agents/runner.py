"""Runs a stored plan in the Docker sandbox and keeps plan/run status in sync."""

from __future__ import annotations

from collections.abc import AsyncIterator

from agents_core.agents.executor import PlanRejected, execute_plan
from agents_core.config import get_config
from agents_core.providers import provider_for
from agents_core.sandbox.docker_runner import DockerSandbox
from agents_core.schemas import AgentEvent, ExecutionReport, Plan
from agents_core.store import repo


def workspace_for(plan: Plan):
    return get_config().workspaces_dir / (plan.conversation_id or plan.id)


async def run_plan(plan: Plan, dry_run: bool = False) -> AsyncIterator[AgentEvent]:
    cfg = get_config()
    llm = provider_for("execute").complete
    report = ExecutionReport(plan_id=plan.id, dry_run=dry_run)
    if not dry_run:
        plan.status = "running"
        repo.save_plan(plan)
    repo.save_run(report)

    yield AgentEvent(type="agent_start", agent="execute", data={"plan_id": plan.id, "workspace": str(workspace_for(plan))})
    try:
        async for item in execute_plan(plan, DockerSandbox(workspace_for(plan), cfg.sandbox), cfg.sandbox, llm=llm, dry_run=dry_run, report=report):
            if isinstance(item, ExecutionReport):
                report = item
            else:
                yield item
    except PlanRejected as e:
        report.status = "failed"
        yield AgentEvent.error("execute", str(e))
    except Exception as e:  # noqa: BLE001 - e.g. Docker not running
        report.status = "failed"
        yield AgentEvent.error("execute", f"execution failed: {type(e).__name__}: {e}")
    finally:
        repo.save_run(report)
        if not dry_run:
            plan.status = {"succeeded": "succeeded", "cancelled": "cancelled"}.get(report.status, "failed")
            repo.save_plan(plan)
    yield AgentEvent(type="agent_end", agent="execute", data={"run_id": report.id, "status": report.status})


def summarize_run(report_events: list[AgentEvent]) -> str:
    """Compact text the orchestrator model sees after running a plan."""
    lines = []
    for ev in report_events:
        if ev.type == "step_end":
            d = ev.data
            line = f"- {d['step_id']}: {d['status']}"
            if d.get("error"):
                line += f" ({d['error']})"
            if d.get("output"):
                line += f"\n  output: {d['output'][-800:]}"
            lines.append(line)
        elif ev.type == "run_end":
            lines.insert(0, f"Run {ev.data['run_id']} finished: {ev.data['status']}")
        elif ev.type == "error":
            lines.append(f"ERROR: {ev.data['message']}")
    return "\n".join(lines) or "no output"
