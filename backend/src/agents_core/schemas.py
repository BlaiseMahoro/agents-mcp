"""Data shapes shared by agents, API, MCP server and the frontend."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator

AgentName = Literal["research", "plan", "execute", "orchestrator"]
ChatMode = Literal["auto", "research", "plan", "execute"]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --- Research -----------------------------------------------------------------


class Source(BaseModel):
    title: str
    url: str


class ResearchReport(BaseModel):
    question: str
    answer_markdown: str = Field(description="The full answer, in markdown, with inline source links.")
    key_findings: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


# --- Plan (the "executable") --------------------------------------------------


class _StepBase(BaseModel):
    id: str = Field(min_length=1, description="Short unique step id, e.g. 's1'.")
    description: str = Field(description="What this step does and why.")
    depends_on: list[str] = Field(default_factory=list, description="Ids of steps that must succeed first.")
    on_failure: Literal["stop", "continue"] = "stop"


class ShellStep(_StepBase):
    type: Literal["shell"]
    command: str = Field(description="Bash command run inside the sandbox, cwd is the workspace root.")


class WriteFileStep(_StepBase):
    type: Literal["write_file"]
    path: str = Field(description="Path relative to the workspace root.")
    content: str


class ReadFileStep(_StepBase):
    type: Literal["read_file"]
    path: str = Field(description="Path relative to the workspace root.")


class LLMTaskStep(_StepBase):
    type: Literal["llm_task"]
    prompt: str = Field(description="Instruction for a language model; outputs of inputs_from steps are appended.")
    inputs_from: list[str] = Field(default_factory=list)


Step = Annotated[ShellStep | WriteFileStep | ReadFileStep | LLMTaskStep, Field(discriminator="type")]
StepType = Literal["shell", "write_file", "read_file", "llm_task"]


class PlanDraft(BaseModel):
    """What the plan agent produces; the server adds identity and status."""

    goal: str
    summary: str = Field(description="One-paragraph overview of the approach.")
    assumptions: list[str] = Field(default_factory=list)
    steps: list[Step]

    @model_validator(mode="after")
    def _check_graph(self) -> PlanDraft:
        validate_step_graph(self.steps)
        return self


class Plan(PlanDraft):
    id: str = Field(default_factory=lambda: new_id("plan"))
    conversation_id: str | None = None
    status: Literal["draft", "approved", "running", "succeeded", "failed", "cancelled"] = "draft"
    created_at: datetime = Field(default_factory=utcnow)


def validate_step_graph(steps: list[Any]) -> None:
    """Reject duplicate ids, unknown dependencies and cycles."""
    ids = [s.id for s in steps]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate step ids: {sorted(dupes)}")
    known = set(ids)
    for s in steps:
        refs = list(s.depends_on) + list(getattr(s, "inputs_from", []))
        missing = [d for d in refs if d not in known]
        if missing:
            raise ValueError(f"step {s.id!r} references unknown steps: {missing}")
    topo_order(steps)


def topo_order(steps: list[Any]) -> list[Any]:
    """Steps in dependency order, keeping the authored order where possible."""
    by_id = {s.id: s for s in steps}
    state: dict[str, int] = {}  # 1 = visiting, 2 = done
    out: list[Any] = []

    def visit(sid: str, path: list[str]) -> None:
        if state.get(sid) == 2:
            return
        if state.get(sid) == 1:
            raise ValueError(f"dependency cycle: {' -> '.join(path + [sid])}")
        state[sid] = 1
        step = by_id[sid]
        for dep in list(step.depends_on) + list(getattr(step, "inputs_from", [])):
            visit(dep, path + [sid])
        state[sid] = 2
        out.append(step)

    for s in steps:
        visit(s.id, [])
    return out


# --- Execution ----------------------------------------------------------------

StepStatus = Literal["pending", "running", "succeeded", "failed", "skipped", "cancelled"]


class StepResult(BaseModel):
    step_id: str
    status: StepStatus = "pending"
    output: str = ""
    error: str = ""
    exit_code: int | None = None
    duration_s: float = 0.0


class ExecutionReport(BaseModel):
    id: str = Field(default_factory=lambda: new_id("run"))
    plan_id: str
    status: Literal["running", "succeeded", "failed", "cancelled"] = "running"
    dry_run: bool = False
    steps: list[StepResult] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None


# --- Event stream -------------------------------------------------------------

EventType = Literal[
    "agent_start",
    "agent_end",
    "text_delta",
    "thinking",
    "tool_call",
    "tool_result",
    "search_result",
    "research_report",
    "plan_ready",
    "approval_required",
    "run_start",
    "step_start",
    "step_output",
    "step_end",
    "run_end",
    "error",
    "done",
]


class AgentEvent(BaseModel):
    """One unit of streamed progress. `data` shape depends on `type`."""

    type: EventType
    agent: AgentName | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def text(cls, agent: AgentName, delta: str) -> AgentEvent:
        return cls(type="text_delta", agent=agent, data={"delta": delta})

    @classmethod
    def error(cls, agent: AgentName | None, message: str) -> AgentEvent:
        return cls(type="error", agent=agent, data={"message": message})
