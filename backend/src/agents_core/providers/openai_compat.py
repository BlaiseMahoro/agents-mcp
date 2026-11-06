"""Open models via any OpenAI-compatible server (Ollama, vLLM, LM Studio)."""

from __future__ import annotations

import json
import os
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx
import openai
from pydantic import ValidationError

from agents_core.config import AgentModelConfig, ProviderConfig
from agents_core.providers.base import ChatMessages, FinalText, ProviderError, T, Tool, ToolResult, call_tool
from agents_core.schemas import AgentEvent, AgentName

STRUCTURED_RETRIES = 2
FINAL_ANSWER_NUDGE = "Now write your final answer for the user, based on everything above."
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


class OpenAICompatProvider:
    supports_native_web_search = False
    thinks_during_structured = False

    def __init__(self, provider: ProviderConfig, agent: AgentModelConfig, client: openai.AsyncOpenAI | None = None):
        self.model = agent.model
        self.reasoning_off_supported = True
        key = os.environ.get(provider.api_key_env, "") if provider.api_key_env else ""
        if provider.auth == "gcp_id_token" and client is None:
            from agents_core.providers.gcp_auth import audience_for, id_token

            try:
                key = id_token(audience_for(provider.base_url or ""))
            except httpx.HTTPError as e:
                raise ProviderError(f"could not get a Google Cloud identity token for the model server: {e}") from e
        self.client = client or openai.AsyncOpenAI(base_url=provider.base_url, api_key=key or "not-needed")

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
        api_tools = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}} for t in tools]
        convo: list[dict[str, Any]] = [{"role": "system", "content": system}, *messages]
        final_text = ""
        used_tools = nudged = False

        for _ in range(max_turns):
            kwargs: dict[str, Any] = {"model": self.model, "messages": convo, "stream": True}
            if api_tools:
                kwargs["tools"] = api_tools
            try:
                stream = await self.client.chat.completions.create(**kwargs)
            except openai.APIConnectionError as e:
                raise ProviderError(f"could not reach model server for {self.model!r}: {e}") from e
            except openai.APIStatusError as e:
                raise ProviderError(f"model server error {e.status_code}: {_detail(e)}") from e

            splitter = ThinkSplitter()
            text, calls = [], {}
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                reasoning = getattr(delta, "reasoning", None) or getattr(delta, "reasoning_content", None)
                if reasoning:
                    yield AgentEvent(type="thinking", agent=agent, data={"delta": reasoning})
                if delta.content:
                    for kind, piece in splitter.feed(delta.content):
                        if kind == "text":
                            text.append(piece)
                            yield AgentEvent.text(agent, piece)
                        else:
                            yield AgentEvent(type="thinking", agent=agent, data={"delta": piece})
                for tc in delta.tool_calls or []:
                    slot = calls.setdefault(tc.index, {"id": tc.id or f"call_{tc.index}", "name": "", "args": ""})
                    if tc.function and tc.function.name:
                        slot["name"] += tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["args"] += tc.function.arguments

            turn_text = "".join(text)
            final_text += turn_text
            if not calls:
                # Small models sometimes finish a tool loop with all their words in reasoning; ask once for the answer.
                if not final_text.strip() and used_tools and not nudged:
                    nudged = True
                    convo.append({"role": "user", "content": FINAL_ANSWER_NUDGE})
                    continue
                break
            used_tools = True

            convo.append({
                "role": "assistant",
                "content": turn_text or None,
                "tool_calls": [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["args"] or "{}"}} for c in calls.values()],
            })
            for c in calls.values():
                yield AgentEvent(type="tool_call", agent=agent, data={"name": c["name"], "input": _loads(c["args"]), "id": c["id"]})
                tool = by_name.get(c["name"])
                outcome = ToolResult(f"unknown tool {c['name']!r}", is_error=True)
                if tool is not None:
                    args = _loads(c["args"])
                    if args is None:
                        outcome = ToolResult("arguments were not valid JSON", is_error=True)
                    else:
                        async for item in call_tool(tool, args):
                            if isinstance(item, ToolResult):
                                outcome = item
                            else:
                                yield item
                yield AgentEvent(type="tool_result", agent=agent, data={"name": c["name"], "id": c["id"], "is_error": outcome.is_error, "preview": outcome.content[:500]})
                content = f"ERROR: {outcome.content}" if outcome.is_error else outcome.content
                convo.append({"role": "tool", "tool_call_id": c["id"], "content": content})
        else:
            raise ProviderError(f"stopped after {max_turns} turns without finishing")

        yield FinalText(final_text)

    async def structured(self, *, system: str, messages: ChatMessages, schema: type[T]) -> T:
        convo: list[dict[str, Any]] = [{"role": "system", "content": system}, *messages]
        response_format = {"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": portable_schema(schema.model_json_schema())}}
        last_error = ""
        for _ in range(STRUCTURED_RETRIES + 1):
            try:
                resp = await self._structured_call(convo, response_format)
            except openai.APIConnectionError as e:
                raise ProviderError(f"could not reach model server for {self.model!r}: {e}") from e
            except openai.APIStatusError as e:
                raise ProviderError(f"model server error {e.status_code}: {_detail(e)}") from e
            msg = resp.choices[0].message
            # Some servers route constrained output into the reasoning channel when thinking stays on.
            raw = msg.content or (msg.model_extra or {}).get("reasoning_content") or ""
            raw = _THINK_RE.sub("", raw).strip()
            raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            try:
                return schema.model_validate_json(raw)
            except ValidationError as e:
                last_error = str(e)
                convo += [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": f"That JSON did not validate:\n{last_error}\nReturn corrected JSON only."},
                ]
        raise ProviderError(f"model did not produce valid {schema.__name__} after {STRUCTURED_RETRIES + 1} tries: {last_error[:500]}")

    async def _structured_call(self, convo: list[dict[str, Any]], response_format: dict[str, Any]):
        """Thinking off for JSON: LM Studio otherwise puts the JSON in reasoning, unconstrained."""
        if self.reasoning_off_supported:
            try:
                return await self.client.chat.completions.create(model=self.model, messages=convo, response_format=response_format, reasoning_effort="none")
            except openai.BadRequestError:
                self.reasoning_off_supported = False  # e.g. a server that rejects "none"
        return await self.client.chat.completions.create(model=self.model, messages=convo, response_format=response_format)

    async def complete(self, prompt: str, system: str = "") -> str:
        final = ""
        async for item in self.run(agent="execute", system=system or "You are a precise assistant.", messages=[{"role": "user", "content": prompt}]):
            if isinstance(item, FinalText):
                final = item.text
        return final


def portable_schema(node: Any) -> Any:
    """Grammar engines (LM Studio MLX, llama.cpp) reject oneOf/discriminator; anyOf is equivalent here
    because pydantic still validates the result against the real schema."""
    if isinstance(node, dict):
        return {("anyOf" if k == "oneOf" else k): portable_schema(v) for k, v in node.items() if k != "discriminator"}
    if isinstance(node, list):
        return [portable_schema(v) for v in node]
    return node


def _detail(e: openai.APIStatusError) -> str:
    """The server's own error text; the SDK message alone is often just 'Error code: 400'."""
    try:
        body = e.response.json()
        err = body.get("error", body)
        return (err.get("message") if isinstance(err, dict) else str(err))[:500]
    except Exception:  # noqa: BLE001
        return (e.response.text or e.message)[:500]


def _loads(raw: str) -> Any:
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return None


class ThinkSplitter:
    """Separates inline <think>…</think> reasoning (Qwen, DeepSeek) from answer text in a stream."""

    def __init__(self) -> None:
        self.buf = ""
        self.in_think = False

    def feed(self, chunk: str) -> list[tuple[str, str]]:
        self.buf += chunk
        out: list[tuple[str, str]] = []
        while self.buf:
            tag = "</think>" if self.in_think else "<think>"
            idx = self.buf.find(tag)
            if idx == -1:
                # keep a possible partial tag at the end for the next chunk
                keep = next((k for k in range(len(tag) - 1, 0, -1) if self.buf.endswith(tag[:k])), 0)
                emit, self.buf = self.buf[: len(self.buf) - keep], self.buf[len(self.buf) - keep :]
                if emit:
                    out.append(("think" if self.in_think else "text", emit))
                break
            if idx:
                out.append(("think" if self.in_think else "text", self.buf[:idx]))
            self.buf = self.buf[idx + len(tag) :]
            self.in_think = not self.in_think
        return out
