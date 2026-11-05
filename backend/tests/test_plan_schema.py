import pytest
from pydantic import ValidationError

from agents_core.schemas import Plan, PlanDraft, topo_order


def _plan(steps):
    return PlanDraft.model_validate({"goal": "g", "summary": "s", "steps": steps})


def test_parses_discriminated_steps():
    p = _plan([
        {"id": "a", "type": "shell", "description": "d", "command": "echo hi"},
        {"id": "b", "type": "write_file", "description": "d", "path": "x.txt", "content": "x", "depends_on": ["a"]},
        {"id": "c", "type": "llm_task", "description": "d", "prompt": "summarize", "inputs_from": ["a"]},
    ])
    assert [s.type for s in p.steps] == ["shell", "write_file", "llm_task"]


def test_rejects_duplicate_ids():
    with pytest.raises(ValidationError, match="duplicate"):
        _plan([{"id": "a", "type": "shell", "description": "", "command": "x"}] * 2)


def test_rejects_unknown_dependency():
    with pytest.raises(ValidationError, match="unknown steps"):
        _plan([{"id": "a", "type": "shell", "description": "", "command": "x", "depends_on": ["zzz"]}])


def test_rejects_cycle():
    with pytest.raises(ValidationError, match="cycle"):
        _plan([
            {"id": "a", "type": "shell", "description": "", "command": "x", "depends_on": ["b"]},
            {"id": "b", "type": "shell", "description": "", "command": "x", "depends_on": ["a"]},
        ])


def test_topo_order_puts_dependencies_first():
    p = _plan([
        {"id": "b", "type": "shell", "description": "", "command": "x", "depends_on": ["a"]},
        {"id": "a", "type": "shell", "description": "", "command": "x"},
    ])
    assert [s.id for s in topo_order(p.steps)] == ["a", "b"]


def test_plan_round_trips_json():
    p = Plan.model_validate({"goal": "g", "summary": "s", "steps": [{"id": "a", "type": "read_file", "description": "", "path": "f"}]})
    assert Plan.model_validate_json(p.model_dump_json()) == p
