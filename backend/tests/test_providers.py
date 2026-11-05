from types import SimpleNamespace as NS

import pytest

from agents_core.config import AgentModelConfig, ProviderConfig
from agents_core.providers.base import FinalText, ProviderError, Tool, ToolResult
from agents_core.providers.openai_compat import OpenAICompatProvider, ThinkSplitter
from agents_core.schemas import AgentEvent, PlanDraft


def test_think_splitter_handles_tags_split_across_chunks():
    sp = ThinkSplitter()
    out = []
    for chunk in ["<thi", "nk>reason", "ing</th", "ink>Hello", " world"]:
        out += sp.feed(chunk)
    think = "".join(t for k, t in out if k == "think")
    text = "".join(t for k, t in out if k == "text")
    assert think == "reasoning"
    assert text == "Hello world"


# --- fake OpenAI-compatible client ---------------------------------------------


def _chunk(content=None, tool_calls=None):
    return NS(choices=[NS(delta=NS(content=content, tool_calls=tool_calls, reasoning=None))])


def _tc(index, id=None, name=None, args=None):
    return NS(index=index, id=id, function=NS(name=name, arguments=args))


class FakeStream:
    def __init__(self, chunks):
        self.chunks = chunks

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for c in self.chunks:
            yield c


class FakeCompletions:
    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        nxt = self.scripted.pop(0)
        return FakeStream(nxt) if kwargs.get("stream") else nxt


def fake_provider(scripted):
    completions = FakeCompletions(scripted)
    client = NS(chat=NS(completions=completions))
    prov = OpenAICompatProvider(ProviderConfig(type="openai_compat", base_url="http://x"), AgentModelConfig(provider="p", model="m"), client=client)
    return prov, completions


async def collect(gen):
    return [x async for x in gen]


async def test_tool_loop_calls_handler_and_feeds_result_back():
    seen = {}

    async def handler(args):
        seen["args"] = args
        yield AgentEvent(type="search_result", agent="research", data={"results": []})
        yield ToolResult("42")

    tool = Tool("lookup", "d", {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}, handler)
    prov, completions = fake_provider([
        [_chunk(tool_calls=[_tc(0, id="c1", name="lookup", args='{"q": ')]), _chunk(tool_calls=[_tc(0, args='"life"}')])],
        [_chunk("<think>hmm</think>The answer"), _chunk(" is 42.")],
    ])
    items = await collect(prov.run(agent="research", system="s", messages=[{"role": "user", "content": "?"}], tools=[tool]))
    assert seen["args"] == {"q": "life"}
    assert isinstance(items[-1], FinalText) and items[-1].text == "The answer is 42."
    types = [i.type for i in items[:-1]]
    assert "tool_call" in types and "search_result" in types and "thinking" in types
    tool_msg = completions.calls[1]["messages"][-1]
    assert tool_msg == {"role": "tool", "tool_call_id": "c1", "content": "42"}


async def test_missing_required_arg_returns_error_to_model():
    async def handler(args):
        yield ToolResult("never")

    tool = Tool("lookup", "d", {"type": "object", "properties": {}, "required": ["q"]}, handler)
    prov, completions = fake_provider([
        [_chunk(tool_calls=[_tc(0, id="c1", name="lookup", args="{}")])],
        [_chunk("ok")],
    ])
    await collect(prov.run(agent="research", system="s", messages=[], tools=[tool]))
    assert completions.calls[1]["messages"][-1]["content"].startswith("ERROR: missing required")


def _resp(text):
    return NS(choices=[NS(message=NS(content=text))])


async def test_structured_retries_on_invalid_json():
    good = '{"goal": "g", "summary": "s", "steps": [{"id": "s1", "type": "shell", "description": "d", "command": "ls"}]}'
    prov, completions = fake_provider([_resp("not json"), _resp(f"<think>x</think>```json\n{good}\n```")])
    plan = await prov.structured(system="s", messages=[{"role": "user", "content": "go"}], schema=PlanDraft)
    assert plan.steps[0].command == "ls"
    assert len(completions.calls) == 2
    assert "did not validate" in completions.calls[1]["messages"][-1]["content"]


async def test_structured_gives_up_after_retries():
    prov, _ = fake_provider([_resp("bad")] * 3)
    with pytest.raises(ProviderError, match="valid PlanDraft"):
        await prov.structured(system="s", messages=[], schema=PlanDraft)


async def test_empty_answer_after_tools_gets_one_nudge():
    async def handler(args):
        yield ToolResult("data")

    tool = Tool("lookup", "d", {"type": "object", "properties": {}, "required": []}, handler)
    prov, completions = fake_provider([
        [_chunk(tool_calls=[_tc(0, id="c1", name="lookup", args="{}")])],
        [_chunk("<think>all my words in here</think>")],
        [_chunk("Final answer.")],
    ])
    items = await collect(prov.run(agent="research", system="s", messages=[], tools=[tool]))
    assert items[-1].text == "Final answer."
    assert completions.calls[2]["messages"][-1]["content"].startswith("Now write your final answer")


def test_portable_schema_has_no_oneof():
    from agents_core.providers.openai_compat import portable_schema

    raw = PlanDraft.model_json_schema()
    assert "oneOf" in str(raw)
    out = str(portable_schema(raw))
    assert "oneOf" not in out and "discriminator" not in out and "anyOf" in out
