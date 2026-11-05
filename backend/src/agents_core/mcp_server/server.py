"""MCP server (stdio) exposing the same agents to Claude Code, Claude Desktop, etc.

Only enabled agents get tools; toggles are read from the shared settings at startup.
Work done here lands in an "MCP session" conversation, so it also shows up in the chat UI.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from agents_core.agents.planner import create_plan as plan_agent
from agents_core.agents.research import research as research_agent
from agents_core.agents.runner import run_plan, summarize_run
from agents_core.providers import ProviderError
from agents_core.sandbox.docker_runner import remove_orphans
from agents_core.schemas import AgentEvent, ResearchReport
from agents_core.store import repo
from agents_core.store.settings import get_settings

_conversation_id: str | None = None


def _conversation() -> str:
    global _conversation_id
    if _conversation_id is None:
        _conversation_id = repo.create_conversation(f"MCP session {datetime.now():%Y-%m-%d %H:%M}").id
    return _conversation_id


async def _log(ctx: Context | None, message: str) -> None:
    if ctx is None:
        return
    result = ctx.info(message)
    if inspect.isawaitable(result):
        await result


async def _drain(ctx: Context | None, events: AsyncIterator[AgentEvent]) -> list[AgentEvent]:
    """Consume an agent stream, forwarding coarse progress to the MCP client log."""
    seen = []
    async for ev in events:
        seen.append(ev)
        if ev.type == "tool_call":
            await _log(ctx, f"{ev.agent}: {ev.data.get('name')} {json.dumps(ev.data.get('input'))[:200]}")
        elif ev.type == "step_end":
            await _log(ctx, f"step {ev.data['step_id']}: {ev.data['status']}")
        elif ev.type == "error":
            raise ProviderError(ev.data["message"])
    return seen


def _record(title: str, events: list[AgentEvent], text: str) -> None:
    conv = _conversation()
    repo.add_message(conv, "user", title, mode="mcp")
    repo.add_message(conv, "assistant", text, mode="mcp", events=[e.model_dump(mode="json") for e in events])


async def research(question: str, ctx: Context | None = None) -> dict[str, Any]:
    """Research a question on the web and return an answer with sources."""
    events = await _drain(ctx, research_agent(question, conversation_id=_conversation()))
    report = next(e.data for e in events if e.type == "research_report")
    _record(question, events, report["answer_markdown"])
    return report


async def create_plan(goal: str, research_report: str | None = None, constraints: str | None = None, ctx: Context | None = None) -> dict[str, Any]:
    """Create an executable step-by-step plan for a goal. Optionally pass research findings (text or JSON report)."""
    report = None
    if research_report:
        try:
            report = ResearchReport.model_validate_json(research_report)
        except ValueError:
            report = ResearchReport(question=goal, answer_markdown=research_report)
    events = await _drain(ctx, plan_agent(goal, conversation_id=_conversation(), research=report, constraints=constraints))
    plan = next(e.data for e in events if e.type == "plan_ready")
    _record(f"Plan: {goal}", events, f"Plan {plan['id']}: {plan['summary']}")
    return plan


async def execute_plan(plan_id: str, dry_run: bool = False, ctx: Context | None = None) -> str:
    """Run a saved plan in the Docker sandbox (dry_run=true only previews). Returns per-step results."""
    plan = repo.get_plan(plan_id)
    if plan is None:
        raise ValueError(f"no plan with id {plan_id}")
    events = await _drain(ctx, run_plan(plan, dry_run=dry_run))
    summary = summarize_run(events)
    _record(f"Execute {plan_id}", events, summary)
    return summary


async def run_pipeline(goal: str, research_first: bool = True, execute: bool = False, ctx: Context | None = None) -> dict[str, Any]:
    """Research (if enabled) -> plan -> optionally execute, skipping agents that are switched off."""
    settings = get_settings()
    out: dict[str, Any] = {}
    report_json = None
    if research_first and settings.is_enabled("research"):
        out["research"] = await research(goal, ctx)
        report_json = json.dumps(out["research"])
    if not settings.is_enabled("plan"):
        out["note"] = "plan agent is switched off; stopped after research"
        return out
    out["plan"] = await create_plan(goal, report_json, ctx=ctx)
    if execute and settings.is_enabled("execute"):
        out["execution"] = await execute_plan(out["plan"]["id"], ctx=ctx)
    return out


def list_agents() -> dict[str, Any]:
    """Which agents are switched on, and which model each uses."""
    s = get_settings()
    return {name: {"enabled": s.enabled.get(name, True), "provider": cfg.provider, "model": cfg.model} for name, cfg in s.agents.items()}


def get_plan(plan_id: str) -> dict[str, Any]:
    """Fetch a saved plan by id."""
    plan = repo.get_plan(plan_id)
    if plan is None:
        raise ValueError(f"no plan with id {plan_id}")
    return plan.model_dump(mode="json")


def list_plans() -> list[dict[str, Any]]:
    """Recent plans: id, goal, status."""
    return [{"id": p.id, "goal": p.goal, "status": p.status, "created_at": p.created_at.isoformat()} for p in repo.list_plans()[:20]]


def build_server() -> MCPServer:
    settings = get_settings()
    server = MCPServer("agents", instructions="Research, plan and execute agents. Plans run in a Docker sandbox.")
    gated = {"research": research, "plan": create_plan, "execute": execute_plan}
    for agent, fn in gated.items():
        if settings.is_enabled(agent):
            server.tool()(fn)
    for fn in (run_pipeline, list_agents, get_plan, list_plans):
        server.tool()(fn)
    return server


def main() -> None:
    remove_orphans()
    build_server().run("stdio")


if __name__ == "__main__":
    main()
