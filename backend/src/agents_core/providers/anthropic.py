"""Claude via the native Anthropic SDK: adaptive thinking, server-side web search."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import anthropic

from agents_core.config import AgentModelConfig, ProviderConfig
from agents_core.providers.base import ChatMessages, FinalText, ProviderError, T, Tool, ToolResult, call_tool
from agents_core.schemas import AgentEvent, AgentName

MAX_TOKENS = 64_000
# Models that accept server-side refusal fallbacks (fallbacks: "default").
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    supports_native_web_search = True
    thinks_during_structured = True

    def __init__(self, provider: ProviderConfig, agent: AgentModelConfig, client: anthropic.AsyncAnthropic | None = None):
        self.model = agent.model
        self.effort = agent.effort
        self.client = client or anthropic.AsyncAnthropic()
        self.use_fallbacks = provider.fallbacks and agent.model in FALLBACK_MODELS

    # --- request plumbing -----------------------------------------------------

    def _stream(self, **kwargs: Any):
        kwargs.setdefault("model", self.model)
        kwargs.setdefault("max_tokens", MAX_TOKENS)
        kwargs.setdefault("thinking", {"type": "adaptive", "display": "summarized"})
        kwargs.setdefault("output_config", {"effort": self.effort})
        if self.use_fallbacks:
            return self.client.beta.messages.stream(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
        return self.client.messages.stream(**kwargs)

    @staticmethod
    def _check_stop(msg: Any) -> None:
        if msg.stop_reason == "refusal":
            details = getattr(msg, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise ProviderError(f"Claude declined this request (category: {category or 'unspecified'}).")

    # --- Provider API ---------------------------------------------------------

    async def run(
        self,
        *,
        agent: AgentName,
        system: str,
        messages: ChatMessages,
        tools: list[Tool] | None = None,
        native_web_search: bool = False,
        max_searches: int = 8,
        max_turns: int = 20,
    ) -> AsyncIterator[AgentEvent | FinalText]:
        tools = tools or []
        by_name = {t.name: t for t in tools}
        api_tools: list[dict[str, Any]] = [
            {"name": t.name, "description": t.description, "input_schema": t.parameters, "eager_input_streaming": True}
            for t in tools
        ]
        if native_web_search:
            api_tools += [
                {"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches},
                {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": max_searches},
            ]
        convo: list[dict[str, Any]] = [dict(m) for m in messages]
        sources: dict[str, dict[str, str]] = {}
        text_parts: list[str] = []

        try:
            for _ in range(max_turns):
                kwargs: dict[str, Any] = {"system": system, "messages": convo}
                if api_tools:
                    kwargs["tools"] = api_tools
                async with self._stream(**kwargs) as stream:
                    async for event in stream:
                        if event.type == "content_block_delta":
                            if event.delta.type == "text_delta":
                                yield AgentEvent.text(agent, event.delta.text)
                            elif event.delta.type == "thinking_delta" and event.delta.thinking:
                                yield AgentEvent(type="thinking", agent=agent, data={"delta": event.delta.thinking})
                    msg = await stream.get_final_message()

                self._check_stop(msg)
                if msg.stop_reason == "max_tokens":
                    raise ProviderError("response hit max_tokens before finishing")

                for block in msg.content:
                    if block.type == "text":
                        text_parts.append(block.text)
                    elif block.type == "server_tool_use":
                        yield AgentEvent(type="tool_call", agent=agent, data={"name": block.name, "input": block.input})
                    elif block.type == "web_search_tool_result":
                        found = _search_results(block)
                        for s in found:
                            sources.setdefault(s["url"], s)
                        yield AgentEvent(type="search_result", agent=agent, data={"results": found})

                convo.append({"role": "assistant", "content": msg.content})
                if msg.stop_reason == "pause_turn":
                    continue  # server tool loop paused; send it back to resume
                if msg.stop_reason != "tool_use":
                    break

                results = []
                for block in msg.content:
                    if block.type != "tool_use":
                        continue
                    tool = by_name.get(block.name)
                    yield AgentEvent(type="tool_call", agent=agent, data={"name": block.name, "input": block.input, "id": block.id})
                    if tool is None:
                        outcome = ToolResult(f"unknown tool {block.name!r}", is_error=True)
                    else:
                        outcome = ToolResult("(no output)")
                        async for item in call_tool(tool, _as_args(block.input)):
                            if isinstance(item, ToolResult):
                                outcome = item
                            else:
                                yield item
                    yield AgentEvent(type="tool_result", agent=agent, data={"name": block.name, "id": block.id, "is_error": outcome.is_error, "preview": outcome.content[:500]})
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": outcome.content, "is_error": outcome.is_error})
                convo.append({"role": "user", "content": results})
            else:
                raise ProviderError(f"stopped after {max_turns} turns without finishing")
        except anthropic.APIConnectionError as e:
            raise ProviderError(f"could not reach the Anthropic API: {e}") from e
        except anthropic.AuthenticationError as e:
            raise ProviderError("Anthropic credentials missing or invalid (set ANTHROPIC_API_KEY or run `ant auth login`)") from e
        except anthropic.RateLimitError as e:
            raise ProviderError("Anthropic rate limit hit; try again shortly") from e
        except anthropic.APIStatusError as e:
            raise ProviderError(f"Anthropic API error {e.status_code}: {e.message}") from e

        yield FinalText("".join(text_parts), sources=list(sources.values()))

    async def structured(self, *, system: str, messages: ChatMessages, schema: type[T]) -> T:
        try:
            async with self._stream(system=system, messages=list(messages), output_format=schema) as stream:
                msg = await stream.get_final_message()
        except anthropic.AuthenticationError as e:
            raise ProviderError("Anthropic credentials missing or invalid (set ANTHROPIC_API_KEY or run `ant auth login`)") from e
        except anthropic.APIStatusError as e:
            raise ProviderError(f"Anthropic API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise ProviderError(f"could not reach the Anthropic API: {e}") from e
        self._check_stop(msg)
        if msg.stop_reason == "max_tokens":
            raise ProviderError("structured response hit max_tokens before finishing")
        parsed = getattr(msg, "parsed_output", None)
        if parsed is None:
            text = "".join(b.text for b in msg.content if b.type == "text")
            parsed = schema.model_validate_json(text)
        return parsed

    async def complete(self, prompt: str, system: str = "") -> str:
        final = ""
        async for item in self.run(agent="execute", system=system or "You are a precise assistant.", messages=[{"role": "user", "content": prompt}]):
            if isinstance(item, FinalText):
                final = item.text
        return final


def _as_args(raw: Any) -> Any:
    if isinstance(raw, str):  # eager input streaming can hand back a raw string
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


def _search_results(block: Any) -> list[dict[str, str]]:
    content = block.content
    if not isinstance(content, list):  # error object, e.g. max_uses_exceeded
        return []
    return [{"title": r.title, "url": r.url} for r in content if getattr(r, "type", "") == "web_search_result"]
