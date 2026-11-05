import pytest

from agents_core.agents.executor import PlanRejected, execute_plan, resolve_in_workspace
from agents_core.config import SandboxConfig
from agents_core.sandbox.docker_runner import docker_available, image_present
from agents_core.schemas import ExecutionReport, Plan

CFG = SandboxConfig(step_timeout_s=5)


def make_plan(steps) -> Plan:
    return Plan.model_validate({"goal": "g", "summary": "s", "steps": steps})


async def run(plan, sandbox, **kw):
    events, report = [], None
    async for item in execute_plan(plan, sandbox, kw.pop("cfg", CFG), **kw):
        if isinstance(item, ExecutionReport):
            report = item
        else:
            events.append(item)
    return events, report


def by_id(report):
    return {s.step_id: s for s in report.steps}


async def test_shell_and_files_round_trip(local_sandbox):
    plan = make_plan([
        {"id": "w", "type": "write_file", "description": "", "path": "src/hello.txt", "content": "hello"},
        {"id": "s", "type": "shell", "description": "", "command": "cat src/hello.txt && echo !", "depends_on": ["w"]},
        {"id": "r", "type": "read_file", "description": "", "path": "src/hello.txt", "depends_on": ["w"]},
    ])
    events, report = await run(plan, local_sandbox)
    assert report.status == "succeeded"
    steps = by_id(report)
    assert steps["s"].output == "hello!\n"
    assert steps["r"].output == "hello"
    assert local_sandbox.started and local_sandbox.stopped
    assert any(e.type == "step_output" for e in events)


async def test_path_escape_is_rejected(local_sandbox):
    plan = make_plan([{"id": "w", "type": "write_file", "description": "", "path": "../../evil.txt", "content": "x"}])
    _, report = await run(plan, local_sandbox)
    assert report.status == "failed"
    assert "escapes the workspace" in by_id(report)["w"].error


def test_resolve_allows_nested_and_absolute_style(tmp_path):
    assert resolve_in_workspace(tmp_path, "/a/b.txt") == (tmp_path / "a/b.txt").resolve()
    with pytest.raises(PlanRejected):
        resolve_in_workspace(tmp_path, "a/../../x")


async def test_stop_on_failure_skips_rest(local_sandbox):
    plan = make_plan([
        {"id": "bad", "type": "shell", "description": "", "command": "exit 3"},
        {"id": "after", "type": "shell", "description": "", "command": "echo nope"},
    ])
    _, report = await run(plan, local_sandbox)
    steps = by_id(report)
    assert steps["bad"].status == "failed" and steps["bad"].exit_code == 3
    assert steps["after"].status == "skipped"
    assert report.status == "failed"


async def test_continue_on_failure_runs_independent_steps_but_skips_dependents(local_sandbox):
    plan = make_plan([
        {"id": "bad", "type": "shell", "description": "", "command": "false", "on_failure": "continue"},
        {"id": "dep", "type": "shell", "description": "", "command": "echo x", "depends_on": ["bad"]},
        {"id": "free", "type": "shell", "description": "", "command": "echo ok"},
    ])
    _, report = await run(plan, local_sandbox)
    steps = by_id(report)
    assert steps["dep"].status == "skipped"
    assert steps["free"].status == "succeeded"


async def test_timeout(local_sandbox):
    plan = make_plan([{"id": "slow", "type": "shell", "description": "", "command": "sleep 5"}])
    _, report = await run(plan, local_sandbox, cfg=SandboxConfig(step_timeout_s=1))
    assert "timed out" in by_id(report)["slow"].error


async def test_disallowed_step_type_rejected_before_running(local_sandbox):
    plan = make_plan([{"id": "s", "type": "shell", "description": "", "command": "echo"}])
    with pytest.raises(PlanRejected):
        await run(plan, local_sandbox, cfg=SandboxConfig(allowed_step_types=["write_file"]))
    assert not local_sandbox.started


async def test_dry_run_does_not_touch_sandbox(local_sandbox):
    plan = make_plan([{"id": "s", "type": "shell", "description": "", "command": "rm -rf /"}])
    _, report = await run(plan, local_sandbox, dry_run=True)
    assert report.status == "succeeded" and report.dry_run
    assert by_id(report)["s"].output == "$ rm -rf /"
    assert not local_sandbox.started


async def test_llm_task_gets_inputs(local_sandbox):
    seen = {}

    async def fake_llm(prompt: str) -> str:
        seen["prompt"] = prompt
        return "summary!"

    plan = make_plan([
        {"id": "a", "type": "shell", "description": "", "command": "echo data-123"},
        {"id": "b", "type": "llm_task", "description": "", "prompt": "Summarize", "inputs_from": ["a"]},
    ])
    _, report = await run(plan, local_sandbox, llm=fake_llm)
    assert by_id(report)["b"].output == "summary!"
    assert "data-123" in seen["prompt"]


docker_ok, _ = docker_available()


@pytest.mark.skipif(not (docker_ok and image_present("agents-sandbox:latest")), reason="Docker or sandbox image unavailable")
async def test_docker_sandbox_end_to_end(tmp_path):
    from agents_core.sandbox.docker_runner import DockerSandbox

    cfg = SandboxConfig(step_timeout_s=30)
    sandbox = DockerSandbox(tmp_path / "ws", cfg)
    plan = make_plan([
        {"id": "w", "type": "write_file", "description": "", "path": "app.py", "content": "print('from container')"},
        {"id": "s", "type": "shell", "description": "", "command": "python app.py && pwd", "depends_on": ["w"]},
    ])
    _, report = await run(plan, sandbox, cfg=cfg)
    assert report.status == "succeeded", report
    assert by_id(report)["s"].output == "from container\n/workspace\n"
