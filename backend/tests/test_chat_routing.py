import pytest

from agents_core.agents import chat, orchestrator
from agents_core.agents.chat import AgentDisabled, handle_turn, transcript_text
from agents_core.providers.base import FinalText
from agents_core.schemas import AgentEvent, PlanDraft
from agents_core.store import repo
from agents_core.store.settings import update_settings


class ScriptedProvider:
    """Provider stand-in: optionally calls one tool, then answers."""

    supports_native_web_search = False
    thinks_during_structured = True

    def __init__(self, call_tool=None, plan=None):
        self.call_tool = call_tool
        self.plan = plan
        self.tools_seen = []

    async def run(self, *, agent, system, messages, tools=None, **kw):
        self.tools_seen = [t.name for t in tools or []]
        if self.call_tool:
            name, args = self.call_tool
            tool = next(t for t in tools if t.name == name)
            async for item in tool.handler(args):
                if not hasattr(item, "content"):
                    yield item
        yield AgentEvent.text(agent, "done")
        yield FinalText("done")

    async def structured(self, *, system, messages, schema):
        return self.plan

    async def complete(self, prompt, system=""):
        return "llm"


PLAN = PlanDraft.model_validate({"goal": "g", "summary": "s", "steps": [{"id": "s1", "type": "shell", "description": "d", "command": "echo hi"}]})


@pytest.fixture
def conv():
    return repo.create_conversation().id


def use_provider(monkeypatch, prov):
    for mod in ("agents_core.agents.orchestrator", "agents_core.agents.planner", "agents_core.agents.research"):
        monkeypatch.setattr(f"{mod}.provider_for", lambda _agent: prov)


async def collect(gen):
    return [e async for e in gen]


async def test_auto_only_offers_enabled_agents(monkeypatch, conv):
    prov = ScriptedProvider()
    use_provider(monkeypatch, prov)
    update_settings({"enabled": {"research": False}})
    await collect(handle_turn(conv, "hi", "auto"))
    assert prov.tools_seen == ["create_plan", "execute_plan"]


async def test_picker_rejects_disabled_agent(conv):
    update_settings({"enabled": {"plan": False}})
    with pytest.raises(AgentDisabled):
        await collect(handle_turn(conv, "make a plan", "plan"))


async def test_plan_mode_saves_plan(monkeypatch, conv):
    use_provider(monkeypatch, ScriptedProvider(plan=PLAN))
    events = await collect(handle_turn(conv, "build it", "plan"))
    ready = next(e for e in events if e.type == "plan_ready")
    assert repo.get_plan(ready.data["id"]).conversation_id == conv
    assert "[Plan" in transcript_text(events)


async def test_auto_execute_waits_for_approval(monkeypatch, conv):
    use_provider(monkeypatch, ScriptedProvider(plan=PLAN))
    await collect(handle_turn(conv, "plan it", "plan"))
    use_provider(monkeypatch, ScriptedProvider(call_tool=("execute_plan", {})))
    events = await collect(handle_turn(conv, "run it", "auto"))
    assert any(e.type == "approval_required" for e in events)
    assert not any(e.type == "run_start" for e in events)


async def test_execute_mode_without_plan_reports_error(conv):
    events = await collect(handle_turn(conv, "go", "execute"))
    assert events[0].type == "error"


async def test_auto_execute_runs_when_approval_off(monkeypatch, conv, local_sandbox):
    use_provider(monkeypatch, ScriptedProvider(plan=PLAN))
    await collect(handle_turn(conv, "plan it", "plan"))
    update_settings({"require_approval": False})
    monkeypatch.setattr("agents_core.agents.runner.DockerSandbox", lambda ws, cfg: local_sandbox)
    monkeypatch.setattr("agents_core.agents.runner.provider_for", lambda _a: ScriptedProvider())
    use_provider(monkeypatch, ScriptedProvider(call_tool=("execute_plan", {})))
    events = await collect(handle_turn(conv, "run it", "auto"))
    end = next(e for e in events if e.type == "run_end")
    assert end.data["status"] == "succeeded"
    assert repo.latest_plan(conv).status == "succeeded"
