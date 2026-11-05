"""Plan agent: turns a goal (plus research) into a validated, executable Plan."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from agents_core.config import get_config
from agents_core.providers import FinalText, Provider, provider_for
from agents_core.providers.base import ChatMessages
from agents_core.schemas import AgentEvent, Plan, PlanDraft, ResearchReport
from agents_core.store import repo

SYSTEM = """You are a planning agent. Produce a plan that an automated executor will run step by step.

Environment the steps run in:
- A fresh Linux container (Debian, Python 3.12, uv, Node.js/npm, git, curl, jq, procps). Network: {network}.
- The working directory is a persistent workspace folder; all paths are relative to it.
- Each `shell` step runs `bash -lc <command>` from the workspace root, with a {timeout}s timeout. No interactive prompts: pass -y / --yes flags.
- Python packages: `uv pip install --system <pkgs>` then `python ...`, or a uv project (`uv init`, `uv add <pkgs>`, `uv run ...`).
- Every shell step is a fresh bash: `cd` and exported variables do not carry over (use paths or `cd dir && ...`).
  All steps of one run share one container, so a background server started in one step stays up for later steps.
  Start servers with output redirected so the step returns, e.g. `nohup uv run uvicorn main:app --port 8000 > server.log 2>&1 &`,
  then `sleep 3` before testing them.
- Allowed step types: {types}.
  - shell: run a command. Prefer small, verifiable commands.
  - write_file: create/overwrite a file with the full content (use this instead of heredocs).
  - read_file: read a file so later llm_task steps can use it.
  - llm_task: ask a language model to reason over earlier steps' outputs (list them in inputs_from).

Rules:
- Give every step a short unique id (s1, s2, ...), a description, and depends_on for real dependencies.
- Use on_failure: "continue" only for optional steps.
- End with a step that verifies the result (run tests, run the program, list files).
- Don't do anything destructive outside the workspace."""


SKETCH_ASK = """

First, think the plan through and write it out as a numbered list. For each step give its type,
exact command/path/content, and which steps it depends on. Remember each shell step starts fresh in the
workspace root. End with a verification step."""


def _context(goal: str, report: ResearchReport | None, constraints: str | None) -> str:
    parts = [f"Goal: {goal}"]
    if constraints:
        parts.append(f"Constraints: {constraints}")
    if report:
        parts.append("Research findings to rely on:\n" + json.dumps(report.model_dump(include={"answer_markdown", "key_findings", "sources"}), ensure_ascii=False))
    return "\n\n".join(parts)


async def create_plan(
    goal: str,
    history: ChatMessages | None = None,
    conversation_id: str | None = None,
    research: ResearchReport | None = None,
    constraints: str | None = None,
    provider: Provider | None = None,
) -> AsyncIterator[AgentEvent]:
    """Stream planning progress; ends with `plan_ready` carrying the saved plan."""
    sandbox = get_config().sandbox
    provider = provider or provider_for("plan")
    if research is None and conversation_id:
        research = repo.latest_report(conversation_id)

    yield AgentEvent(type="agent_start", agent="plan", data={"goal": goal, "uses_research": research is not None})
    system = SYSTEM.format(network="on" if sandbox.network else "off", timeout=sandbox.step_timeout_s, types=", ".join(sandbox.allowed_step_types))
    messages = [*(history or []), {"role": "user", "content": _context(goal, research, constraints)}]

    if not provider.thinks_during_structured:
        # Local models answer JSON with thinking off, so let them reason in prose first.
        sketch = ""
        async for item in provider.run(agent="plan", system=system, messages=[*messages[:-1], {"role": "user", "content": messages[-1]["content"] + SKETCH_ASK}]):
            if isinstance(item, FinalText):
                sketch = item.text
            elif item.type in ("text_delta", "thinking"):
                yield AgentEvent(type="thinking", agent="plan", data={"delta": item.data["delta"]})
        messages += [{"role": "assistant", "content": sketch}, {"role": "user", "content": "Now output that plan as JSON matching the schema exactly."}]

    draft = await provider.structured(system=system, messages=messages, schema=PlanDraft)
    plan = Plan(**draft.model_dump(), conversation_id=conversation_id)
    repo.save_plan(plan)
    yield AgentEvent(type="plan_ready", agent="plan", data=plan.model_dump(mode="json"))
    yield AgentEvent(type="agent_end", agent="plan")
