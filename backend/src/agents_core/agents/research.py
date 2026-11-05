"""Research agent: searches the web, reads sources, reasons to an answer."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date

from pydantic import BaseModel, Field

from agents_core.config import get_config
from agents_core.providers import FinalText, Provider, provider_for
from agents_core.providers.base import ChatMessages
from agents_core.schemas import AgentEvent, ResearchReport, Source
from agents_core.store import repo
from agents_core.store.settings import get_settings
from agents_core.tools.search import search_tools

SYSTEM = """You are a research agent. Today is {today}.
Answer the user's question by searching the web and reading sources.
- Run several focused searches; open the most promising pages to read them rather than trusting snippets.
- Cross-check important facts across independent sources and note disagreements.
- Reason step by step to a conclusion; say plainly what is uncertain.
- Finish with a clear markdown answer that cites sources inline as [title](url)."""

EXTRACT = """Summarize this research answer into key findings, the sources it relied on (copy titles and URLs
exactly from the list), and any open questions."""


async def research(
    question: str,
    history: ChatMessages | None = None,
    conversation_id: str | None = None,
    provider: Provider | None = None,
) -> AsyncIterator[AgentEvent]:
    """Stream research progress; ends with a `research_report` event."""
    cfg = get_config()
    agent_cfg = get_settings().agents["research"]
    provider = provider or provider_for("research")
    native = agent_cfg.search == "native" and provider.supports_native_web_search
    sources: dict[str, dict[str, str]] = {}
    tools = [] if native else search_tools(cfg.search, agent_cfg.max_searches, sources)

    yield AgentEvent(type="agent_start", agent="research", data={"question": question, "search": "native" if native else "searxng"})
    messages = [*(history or []), {"role": "user", "content": question}]
    answer = ""
    async for item in provider.run(
        agent="research",
        system=SYSTEM.format(today=date.today().isoformat()),
        messages=messages,
        tools=tools,
        native_web_search=native,
        max_searches=agent_cfg.max_searches,
    ):
        if isinstance(item, FinalText):
            answer = item.text
            for s in item.sources:
                sources.setdefault(s["url"], s)
        else:
            yield item

    report = await _structure(provider, question, answer, sources)
    report_id = repo.save_report(report, conversation_id)
    yield AgentEvent(type="research_report", agent="research", data={"id": report_id, **report.model_dump()})
    yield AgentEvent(type="agent_end", agent="research")


class _ReportExtras(BaseModel):
    """Only what the streamed answer doesn't already give us; required so grammar-constrained models fill them."""

    key_findings: list[str] = Field(min_length=1, max_length=8, description="Concrete facts the answer established.")
    sources_used: list[Source] = Field(description="Sources the answer actually relied on, from the list provided.")
    open_questions: list[str] = Field(max_length=5, description="What remains uncertain; empty if nothing.")


async def _structure(provider: Provider, question: str, answer: str, sources: dict[str, dict[str, str]]) -> ResearchReport:
    """Second pass that pulls findings and sources out of the answer; falls back to the raw answer."""
    seen = [Source(**s) for s in sources.values()]
    listing = "\n".join(f"- {s.title}: {s.url}" for s in seen)
    try:
        extras = await provider.structured(
            system=EXTRACT,
            messages=[{"role": "user", "content": f"Question: {question}\n\nAnswer:\n{answer}\n\nSources seen:\n{listing}"}],
            schema=_ReportExtras,
        )
    except Exception:  # noqa: BLE001 - structuring is best effort; the answer already streamed
        return ResearchReport(question=question, answer_markdown=answer, sources=seen)
    return ResearchReport(
        question=question,
        answer_markdown=answer,
        key_findings=extras.key_findings,
        sources=extras.sources_used or seen,
        open_questions=extras.open_questions,
    )
