"""Auto mode: one assistant that decides when to call the enabled agents."""

from __future__ import annotations

from collections.abc import AsyncIterator

from agents_core.agents.planner import create_plan
from agents_core.agents.research import research
from agents_core.agents.runner import run_plan, summarize_run
from agents_core.providers import FinalText, Provider, Tool, ToolResult, provider_for
from agents_core.providers.base import ChatMessages
from agents_core.schemas import AgentEvent
from agents_core.store import repo
from agents_core.store.settings import get_settings

SYSTEM = """You are the coordinator of three specialist agents. Help the user directly when you can;
call a specialist when the request needs it.
Available specialists (only these are switched on): {available}.
- research: web research with sources. Use for anything needing current or external facts.
- create_plan: turn a goal into an executable step-by-step plan (runs in a Linux sandbox). It automatically
  uses the latest research in this conversation.
- execute_plan: run the latest plan.{approval}
After a specialist finishes, give the user a short summary of the result and the sensible next step.
If a capability is switched off, say so instead of improvising it."""

APPROVAL_NOTE = " Plans need the user's approval: calling it shows them a 'Run plan' button; do not claim it ran."


def build_tools(conversation_id: str) -> list[Tool]:
    settings = get_settings()
    tools: list[Tool] = []

    if settings.is_enabled("research"):
        async def do_research(args):
            report = None
            async for ev in research(args["question"], conversation_id=conversation_id):
                if ev.type == "research_report":
                    report = ev.data
                yield ev
            if report:
                sources = "\n".join(f"- {s['title']}: {s['url']}" for s in report["sources"][:10])
                yield ToolResult(f"{report['answer_markdown']}\n\nSources:\n{sources}")

        tools.append(Tool("research", "Research a question on the web; returns an answer with sources.",
                          {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}, do_research))

    if settings.is_enabled("plan"):
        async def do_plan(args):
            plan = None
            async for ev in create_plan(args["goal"], conversation_id=conversation_id, constraints=args.get("constraints")):
                if ev.type == "plan_ready":
                    plan = ev.data
                yield ev
            if plan:
                steps = "\n".join(f"{s['id']}. {s['description']}" for s in plan["steps"])
                yield ToolResult(f"Plan {plan['id']} created: {plan['summary']}\nSteps:\n{steps}")

        tools.append(Tool("create_plan", "Create an executable plan for a goal.",
                          {"type": "object", "properties": {"goal": {"type": "string"}, "constraints": {"type": "string"}}, "required": ["goal"]}, do_plan))

    if settings.is_enabled("execute"):
        async def do_execute(args):
            plan = repo.latest_plan(conversation_id)
            if plan is None:
                yield ToolResult("There is no plan in this conversation yet. Create one first.", is_error=True)
                return
            if get_settings().require_approval and args.get("dry_run") is not True:
                yield AgentEvent(type="approval_required", agent="execute", data={"plan_id": plan.id})
                yield ToolResult(f"Plan {plan.id} is waiting for the user to approve it with the 'Run plan' button.")
                return
            events = []
            async for ev in run_plan(plan, dry_run=bool(args.get("dry_run"))):
                events.append(ev)
                yield ev
            yield ToolResult(summarize_run(events))

        tools.append(Tool("execute_plan", "Run the latest plan in this conversation (dry_run=true only previews it).",
                          {"type": "object", "properties": {"dry_run": {"type": "boolean"}}, "required": []}, do_execute))
    return tools


async def orchestrate(conversation_id: str, message: str, history: ChatMessages, provider: Provider | None = None) -> AsyncIterator[AgentEvent]:
    settings = get_settings()
    tools = build_tools(conversation_id)
    available = ", ".join(t.name for t in tools) or "none"
    system = SYSTEM.format(available=available, approval=APPROVAL_NOTE if settings.require_approval else "")
    provider = provider or provider_for("orchestrator")

    yield AgentEvent(type="agent_start", agent="orchestrator")
    async for item in provider.run(agent="orchestrator", system=system, messages=[*history, {"role": "user", "content": message}], tools=tools):
        if not isinstance(item, FinalText):
            yield item
    yield AgentEvent(type="agent_end", agent="orchestrator")
