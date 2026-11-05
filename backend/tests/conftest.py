import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agents_core.sandbox.docker_runner import ExecChunk, ExecDone


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Point config + SQLite at a temp dir for every test."""
    from agents_core import config
    from agents_core.store import db

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        (config.REPO_ROOT / "config.yaml").read_text().replace("data_dir: data", f"data_dir: {tmp_path / 'data'}")
    )
    monkeypatch.setenv("AGENTS_CONFIG", str(cfg_file))
    config.get_config.cache_clear()
    db.engine.cache_clear()
    yield
    config.get_config.cache_clear()
    db.engine.cache_clear()


class LocalSandbox:
    """Runs commands with a local bash in a temp dir; stands in for Docker in unit tests."""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.started = self.stopped = False

    async def start(self) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.started = True

    async def exec(self, command: str, timeout_s: int) -> AsyncIterator[ExecChunk | ExecDone]:
        proc = await asyncio.create_subprocess_exec(
            "bash", "-c", command, cwd=self.workspace, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout_s)
        except TimeoutError:
            proc.kill()
            yield ExecDone(exit_code=124, timed_out=True)
            return
        if out:
            yield ExecChunk("stdout", out.decode())
        if err:
            yield ExecChunk("stderr", err.decode())
        yield ExecDone(exit_code=proc.returncode, timed_out=False)

    async def stop(self) -> None:
        self.stopped = True


@pytest.fixture
def local_sandbox(tmp_path):
    return LocalSandbox(tmp_path / "ws")
