"""Throwaway Docker container per run, with the conversation workspace mounted."""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from agents_core.config import SandboxConfig

WORKDIR = "/workspace"
TIMEOUT_EXIT = 124  # what coreutils `timeout` returns


@dataclass
class ExecChunk:
    stream: str  # "stdout" | "stderr"
    text: str


@dataclass
class ExecDone:
    exit_code: int
    timed_out: bool


class Sandbox(Protocol):
    workspace: Path

    async def start(self) -> None: ...
    def exec(self, command: str, timeout_s: int) -> AsyncIterator[ExecChunk | ExecDone]: ...
    async def stop(self) -> None: ...


class DockerSandbox:
    def __init__(self, workspace: Path, cfg: SandboxConfig):
        self.workspace = workspace
        self.cfg = cfg
        self._container = None
        self._client = None

    async def start(self) -> None:
        import docker  # imported lazily so tests without Docker can still import this module

        self.workspace.mkdir(parents=True, exist_ok=True)
        self._client = docker.from_env()
        self._container = await asyncio.to_thread(
            self._client.containers.run,
            self.cfg.image,
            command=["sleep", "infinity"],
            detach=True,
            working_dir=WORKDIR,
            volumes={str(self.workspace.resolve()): {"bind": WORKDIR, "mode": "rw"}},
            nano_cpus=int(self.cfg.cpus * 1e9),
            mem_limit=self.cfg.memory,
            network_disabled=not self.cfg.network,
            labels={"app": "agents-mcp", "owner_pid": str(os.getpid())},
        )

    async def exec(self, command: str, timeout_s: int) -> AsyncIterator[ExecChunk | ExecDone]:
        assert self._container is not None and self._client is not None, "sandbox not started"
        api = self._client.api
        wrapped = ["timeout", "--kill-after=5", str(timeout_s), "bash", "-lc", command]
        exec_id = await asyncio.to_thread(api.exec_create, self._container.id, wrapped, workdir=WORKDIR)
        queue: asyncio.Queue[ExecChunk | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def pump() -> None:
            try:
                for out, err in api.exec_start(exec_id, stream=True, demux=True):
                    if out:
                        loop.call_soon_threadsafe(queue.put_nowait, ExecChunk("stdout", out.decode(errors="replace")))
                    if err:
                        loop.call_soon_threadsafe(queue.put_nowait, ExecChunk("stderr", err.decode(errors="replace")))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        threading.Thread(target=pump, daemon=True).start()
        while (chunk := await queue.get()) is not None:
            yield chunk
        info = await asyncio.to_thread(api.exec_inspect, exec_id)
        code = info.get("ExitCode")
        code = -1 if code is None else int(code)
        yield ExecDone(exit_code=code, timed_out=code in (TIMEOUT_EXIT, 137))

    async def stop(self) -> None:
        if self._container is not None:
            try:
                await asyncio.to_thread(self._container.remove, force=True)
            finally:
                self._container = None


def remove_orphans() -> int:
    """Remove sandbox containers whose owning process died mid-run (crash, reload). Best effort."""
    try:
        import docker

        removed = 0
        for c in docker.from_env().containers.list(all=True, filters={"label": "app=agents-mcp"}):
            pid = int(c.labels.get("owner_pid", "0") or 0)
            if pid and _alive(pid):
                continue
            c.remove(force=True)
            removed += 1
        return removed
    except Exception:  # noqa: BLE001 - Docker may simply be off
        return 0


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def docker_available() -> tuple[bool, str]:
    try:
        import docker

        docker.from_env().ping()
        return True, "ok"
    except Exception as e:  # noqa: BLE001 - surfaced to the health endpoint
        return False, str(e).splitlines()[0][:200]


def image_present(image: str) -> bool:
    try:
        import docker

        docker.from_env().images.get(image)
        return True
    except Exception:  # noqa: BLE001
        return False

