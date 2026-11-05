"""Provider-neutral interface every agent talks to.

Each provider owns its own tool-calling loop because Anthropic and
OpenAI-compatible APIs shape tool calls and results differently.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from agents_core.schemas import AgentEvent, AgentName

T = TypeVar("T", bound=BaseModel)

# Conversation history in neutral form: [{"role": "user"|"assistant", "content": str}]
ChatMessages = list[dict[str, str]]


@dataclass
class ToolResult:
    """Final item a tool handler yields; becomes the tool_result the model sees."""

    content: str
    is_error: bool = False


# A tool handler may stream progress (AgentEvents) before its ToolResult.
ToolHandler = Callable[[dict[str, Any]], AsyncIterator[AgentEvent | ToolResult]]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema for the arguments
    handler: ToolHandler


@dataclass
class FinalText:
    """Last item of Provider.run(): the assistant's full visible answer."""

    text: str
    sources: list[dict[str, str]] = field(default_factory=list)  # web sources seen (native search)


class ProviderError(RuntimeError):
    pass


class Provider(Protocol):
    supports_native_web_search: bool
    thinks_during_structured: bool  # False: planner sketches in prose before asking for JSON

    def run(
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
        """Stream a tool-using turn until the model stops; ends with FinalText."""
        ...

    async def structured(self, *, system: str, messages: ChatMessages, schema: type[T]) -> T:
        """One call whose answer must validate against `schema`."""
        ...

    async def complete(self, prompt: str, system: str = "") -> str: ...


def check_args(tool: Tool, args: Any) -> str | None:
    """Minimal validation of streamed tool input against the declared schema."""
    if not isinstance(args, dict):
        return "tool input must be a JSON object"
    missing = [k for k in tool.parameters.get("required", []) if k not in args]
    if missing:
        return f"missing required arguments: {missing}"
    return None


async def call_tool(tool: Tool, args: Any) -> AsyncIterator[AgentEvent | ToolResult]:
    """Run a tool handler, turning bad input or exceptions into an error result."""
    if err := check_args(tool, args):
        yield ToolResult(err, is_error=True)
        return
    try:
        got_result = False
        async for item in tool.handler(args):
            if isinstance(item, ToolResult):
                got_result = True
            yield item
        if not got_result:
            yield ToolResult("(no output)")
    except Exception as e:  # noqa: BLE001 - reported back to the model
        yield ToolResult(f"{type(e).__name__}: {e}", is_error=True)


AsyncTextFn = Callable[[str], Awaitable[str]]
