"""HTTP API for the chat UI. Agent progress streams as Server-Sent Events."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ValidationError
from sse_starlette.sse import EventSourceResponse

from agents_core.agents.chat import AgentDisabled, handle_turn, transcript_text
from agents_core.agents.executor import request_cancel
from agents_core.agents.runner import run_plan
from agents_core.config import get_config
from agents_core.sandbox.docker_runner import docker_available, image_present, remove_orphans
from agents_core.schemas import AgentEvent, ChatMode, Plan, PlanDraft
from agents_core.store import repo
from agents_core.store.settings import get_settings, update_settings
from agents_core.tools.search import searxng_ok

@asynccontextmanager
async def lifespan(_app: FastAPI):
    await asyncio.to_thread(remove_orphans)
    yield


app = FastAPI(title="agents-mcp", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

CLAUDE_MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"]


# --- helpers ------------------------------------------------------------------


def _sse(events: AsyncIterator[AgentEvent], on_done) -> EventSourceResponse:
    """Stream events to the browser and persist them when the stream ends (or the client leaves)."""

    async def gen():
        seen: list[AgentEvent] = []
        try:
            async for ev in events:
                seen.append(ev)
                yield {"data": ev.model_dump_json()}
        except Exception as e:  # noqa: BLE001 - shown in the chat instead of a dead stream
            ev = AgentEvent.error(None, f"{type(e).__name__}: {e}")
            seen.append(ev)
            yield {"data": ev.model_dump_json()}
        finally:
            on_done(seen)
        yield {"data": AgentEvent(type="done").model_dump_json()}

    return EventSourceResponse(gen(), ping=15)


def _message_out(m) -> dict[str, Any]:
    return {"id": m.id, "role": m.role, "mode": m.mode, "content": m.content, "events": m.events, "created_at": m.created_at}


# --- health / settings / models -----------------------------------------------


@app.get("/api/health")
async def health() -> dict[str, Any]:
    cfg = get_config()
    docker_ok, docker_msg = docker_available()
    search_ok, search_msg = await searxng_ok(cfg.search)
    providers = {}
    async with httpx.AsyncClient(timeout=3) as client:
        for name, p in cfg.providers.items():
            if p.type == "openai_compat":
                try:
                    r = await client.get(f"{p.base_url.rstrip('/')}/models")
                    providers[name] = {"ok": r.status_code == 200, "detail": "ok" if r.status_code == 200 else f"HTTP {r.status_code}"}
                except httpx.HTTPError as e:
                    providers[name] = {"ok": False, "detail": f"not reachable at {p.base_url} ({type(e).__name__})"}
            else:
                providers[name] = {"ok": True, "detail": "cloud API (checked on first use)"}
    return {
        "docker": {"ok": docker_ok, "detail": docker_msg},
        "sandbox_image": {"ok": image_present(cfg.sandbox.image), "detail": cfg.sandbox.image},
        "searxng": {"ok": search_ok, "detail": search_msg},
        "providers": providers,
    }


@app.get("/api/settings")
def read_settings() -> dict[str, Any]:
    return {**get_settings().model_dump(), "providers": list(get_config().providers)}


@app.put("/api/settings")
def write_settings(patch: dict[str, Any]) -> dict[str, Any]:
    try:
        update_settings(patch)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return read_settings()


@app.get("/api/models")
async def models() -> dict[str, list[str]]:
    """Models each provider offers, for the per-agent model picker."""
    out: dict[str, list[str]] = {}
    async with httpx.AsyncClient(timeout=3) as client:
        for name, p in get_config().providers.items():
            if p.type == "anthropic":
                out[name] = CLAUDE_MODELS
                continue
            try:
                r = await client.get(f"{p.base_url.rstrip('/')}/models")
                out[name] = sorted(m["id"] for m in r.json().get("data", []) if "embed" not in m["id"])
            except (httpx.HTTPError, ValueError, KeyError):
                out[name] = []
    return out


# --- conversations ------------------------------------------------------------


@app.get("/api/conversations")
def conversations() -> list[dict[str, Any]]:
    return [c.model_dump() for c in repo.list_conversations()]


@app.post("/api/conversations")
def new_conversation() -> dict[str, Any]:
    return repo.create_conversation().model_dump()


@app.get("/api/conversations/{conv_id}")
def conversation(conv_id: str) -> dict[str, Any]:
    conv = repo.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404, "conversation not found")
    return {**conv.model_dump(), "messages": [_message_out(m) for m in repo.list_messages(conv_id)]}


@app.delete("/api/conversations/{conv_id}")
def delete_conversation(conv_id: str) -> dict[str, bool]:
    repo.delete_conversation(conv_id)
    return {"ok": True}


class MessageIn(BaseModel):
    content: str
    mode: ChatMode = "auto"


@app.post("/api/conversations/{conv_id}/messages")
async def send_message(conv_id: str, body: MessageIn):
    conv = repo.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404, "conversation not found")
    if body.mode != "auto" and not get_settings().is_enabled(body.mode):
        raise HTTPException(409, f"the {body.mode} agent is switched off")

    stream = handle_turn(conv_id, body.content, body.mode)  # reads history before we add this message
    first = await _prime(stream)
    repo.add_message(conv_id, "user", body.content, mode=body.mode)
    if conv.title == "New chat":
        repo.rename_conversation(conv_id, body.content.strip().splitlines()[0][:60] or "New chat")

    def save(events: list[AgentEvent]) -> None:
        repo.add_message(conv_id, "assistant", transcript_text(events), mode=body.mode, events=[e.model_dump(mode="json") for e in events])

    return _sse(first, save)


async def _prime(stream: AsyncIterator[AgentEvent]) -> AsyncIterator[AgentEvent]:
    """Pull the first event now so AgentDisabled becomes a 409 instead of a broken stream."""
    try:
        head = await anext(stream)
    except StopAsyncIteration:
        head = None
    except AgentDisabled as e:
        raise HTTPException(409, str(e)) from e

    async def chained():
        if head is not None:
            yield head
        async for ev in stream:
            yield ev

    return chained()


# --- plans / runs ---------------------------------------------------------------


@app.get("/api/plans/{plan_id}")
def read_plan(plan_id: str) -> dict[str, Any]:
    plan = repo.get_plan(plan_id)
    if not plan:
        raise HTTPException(404, "plan not found")
    return plan.model_dump(mode="json")


@app.put("/api/plans/{plan_id}")
def edit_plan(plan_id: str, body: dict[str, Any]) -> dict[str, Any]:
    plan = repo.get_plan(plan_id)
    if not plan:
        raise HTTPException(404, "plan not found")
    if plan.status == "running":
        raise HTTPException(409, "plan is running")
    try:
        draft = PlanDraft.model_validate({**plan.model_dump(include={"goal", "summary", "assumptions"}), **body})
    except ValidationError as e:
        raise HTTPException(422, e.errors(include_url=False, include_context=False)) from e
    updated = Plan(**draft.model_dump(), id=plan.id, conversation_id=plan.conversation_id, created_at=plan.created_at)
    repo.save_plan(updated)
    return updated.model_dump(mode="json")


@app.post("/api/plans/{plan_id}/execute")
async def execute(plan_id: str, dry_run: bool = False):
    if not get_settings().is_enabled("execute"):
        raise HTTPException(409, "the execute agent is switched off")
    plan = repo.get_plan(plan_id)
    if not plan:
        raise HTTPException(404, "plan not found")
    if plan.status == "running":
        raise HTTPException(409, "plan is already running")

    def save(events: list[AgentEvent]) -> None:
        if plan.conversation_id:
            repo.add_message(plan.conversation_id, "assistant", transcript_text(events), mode="execute", events=[e.model_dump(mode="json") for e in events])

    return _sse(run_plan(plan, dry_run=dry_run), save)


@app.get("/api/runs/{run_id}")
def read_run(run_id: str) -> dict[str, Any]:
    run = repo.get_run(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    return run.model_dump(mode="json")


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> dict[str, bool]:
    return {"cancelled": request_cancel(run_id)}


def run() -> None:
    import uvicorn

    uvicorn.run("agents_core.api.main:app", host="127.0.0.1", port=8000, reload=False)

