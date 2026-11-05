"""Web search + page fetch for models without native search (SearXNG backend)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
import trafilatura

from agents_core.config import SearchConfig
from agents_core.providers.base import Tool, ToolResult
from agents_core.schemas import AgentEvent

USER_AGENT = "Mozilla/5.0 (agents-mcp research agent)"


async def searxng_search(cfg: SearchConfig, query: str) -> list[dict[str, str]]:
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{cfg.searxng_url.rstrip('/')}/search", params={"q": query, "format": "json"})
        r.raise_for_status()
    results = r.json().get("results", [])[: cfg.max_results]
    return [{"title": x.get("title", ""), "url": x.get("url", ""), "snippet": x.get("content", "")} for x in results]


async def fetch_readable(cfg: SearchConfig, url: str) -> str:
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        r = await client.get(url)
        r.raise_for_status()
    text = trafilatura.extract(r.text, include_links=False, include_tables=True) or r.text
    if len(text) > cfg.fetch_max_chars:
        text = text[: cfg.fetch_max_chars] + "\n…[truncated]"
    return text


def search_tools(cfg: SearchConfig, budget: int, sources: dict[str, dict[str, str]]) -> list[Tool]:
    """web_search + fetch_url tools; `sources` collects every result the agent saw."""
    calls = {"n": 0}

    async def web_search(args: dict) -> AsyncIterator[AgentEvent | ToolResult]:
        calls["n"] += 1
        if calls["n"] > budget:
            yield ToolResult(f"search budget of {budget} used up; answer with what you have", is_error=True)
            return
        results = await searxng_search(cfg, args["query"])
        for x in results:
            sources.setdefault(x["url"], {"title": x["title"], "url": x["url"]})
        yield AgentEvent(type="search_result", agent="research", data={"query": args["query"], "results": [{"title": x["title"], "url": x["url"]} for x in results]})
        yield ToolResult(json.dumps(results, ensure_ascii=False) if results else "no results")

    async def fetch_url(args: dict) -> AsyncIterator[AgentEvent | ToolResult]:
        yield ToolResult(await fetch_readable(cfg, args["url"]))

    return [
        Tool(
            name="web_search",
            description="Search the web. Returns a JSON list of {title, url, snippet}. Use several focused queries.",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            handler=web_search,
        ),
        Tool(
            name="fetch_url",
            description="Fetch a web page and return its main readable text. Use on promising search results.",
            parameters={"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
            handler=fetch_url,
        ),
    ]


async def searxng_ok(cfg: SearchConfig) -> tuple[bool, str]:
    try:
        await searxng_search(cfg, "test")
        return True, "ok"
    except Exception as e:  # noqa: BLE001 - surfaced to the health endpoint
        return False, str(e)[:200]
