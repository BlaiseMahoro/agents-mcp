"""Entry point for one chat turn: routes by the picker mode (auto or a specific agent)."""

from __future__ import annotations

from collections.abc import AsyncIterator

from agents_core.agents.orchestrator import orchestrate
from agents_core.agents.planner import create_plan
from agents_core.agents.research import research
from agents_core.agents.runner import run_plan
from agents_core.providers import ProviderError
from agents_core.providers.base import ChatMessages
from agents_core.schemas import AgentEvent, ChatMode
from agents_core.store import repo
from agents_core.store.settings import get_settings

HISTORY_TURNS = 20


class AgentDisabled(Exception):
    pass


def history_for(conversation_id: str) -> ChatMessages:
    msgs = repo.list_messages(conversation_id)[-HISTORY_TURNS:]
    return [{"role": m.role, "content": m.content} for m in msgs if m.content]


async def handle_turn(conversation_id: str, content: str, mode: ChatMode) -> AsyncIterator[AgentEvent]:
    """Stream every event for one user message. History excludes the message itself."""
    settings = get_settings()
    if mode != "auto" and not settings.is_enabled(mode):
        raise AgentDisabled(f"the {mode} agent is switched off")
    history = history_for(conversation_id)
    try:
        match mode:
            case "auto":
                stream = orchestrate(conversation_id, content, history)
            case "research":
                stream = research(content, history=history, conversation_id=conversation_id)
            case "plan":
                stream = create_plan(content, history=history, conversation_id=conversation_id)
            case "execute":
                plan = repo.latest_plan(conversation_id)
                if plan is None:
                    yield AgentEvent.error("execute", "There is no plan in this conversation yet. Ask the plan agent for one first.")
                    return
                # Choosing the Execute agent and sending a message counts as approval.
                stream = run_plan(plan, dry_run="dry run" in content.lower())
        async for ev in stream:
            yield ev
    except ProviderError as e:
        yield AgentEvent.error(None if mode == "auto" else mode, str(e))


def transcript_text(events: list[AgentEvent]) -> str:
    """What to store as the assistant message text, so later turns have context."""
    out: list[str] = []
    for ev in events:
        if ev.type == "text_delta":
            out.append(ev.data["delta"])
        elif ev.type == "plan_ready":
            steps = "; ".join(f"{s['id']}: {s['description']}" for s in ev.data["steps"])
            out.append(f"\n[Plan {ev.data['id']} created: {ev.data['summary']} Steps: {steps}]\n")
        elif ev.type == "run_end":
            out.append(f"\n[Run {ev.data['run_id']} finished: {ev.data['status']}]\n")
        elif ev.type == "error":
            out.append(f"\n[Error: {ev.data['message']}]\n")
    return "".join(out).strip()
