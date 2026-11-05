import json

from fastapi.testclient import TestClient

from agents_core.api.main import app
from agents_core.schemas import AgentEvent

client = TestClient(app)


def sse_events(resp) -> list[dict]:
    return [json.loads(line[5:].strip()) for line in resp.text.splitlines() if line.startswith("data:")]


def test_settings_toggle_round_trip():
    s = client.get("/api/settings").json()
    assert s["enabled"]["research"] is True
    s = client.put("/api/settings", json={"enabled": {"research": False}, "require_approval": False}).json()
    assert s["enabled"]["research"] is False and s["require_approval"] is False
    assert client.put("/api/settings", json={"agents": {"plan": {"provider": "nope"}}}).status_code == 400


def test_message_to_disabled_agent_is_409():
    conv = client.post("/api/conversations").json()
    client.put("/api/settings", json={"enabled": {"plan": False}})
    r = client.post(f"/api/conversations/{conv['id']}/messages", json={"content": "x", "mode": "plan"})
    assert r.status_code == 409


def test_message_streams_and_persists(monkeypatch):
    async def fake_turn(conv_id, content, mode):
        yield AgentEvent(type="agent_start", agent="research")
        yield AgentEvent.text("research", "hello ")
        yield AgentEvent.text("research", "there")

    monkeypatch.setattr("agents_core.api.main.handle_turn", fake_turn)
    conv = client.post("/api/conversations").json()
    r = client.post(f"/api/conversations/{conv['id']}/messages", json={"content": "Find FastAPI version", "mode": "research"})
    events = sse_events(r)
    assert [e["type"] for e in events] == ["agent_start", "text_delta", "text_delta", "done"]
    detail = client.get(f"/api/conversations/{conv['id']}").json()
    assert detail["title"] == "Find FastAPI version"
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["content"] == "hello there"


def test_plan_edit_validates():
    from agents_core.schemas import Plan
    from agents_core.store import repo

    plan = repo.save_plan(Plan.model_validate({"goal": "g", "summary": "s", "steps": [{"id": "a", "type": "shell", "description": "", "command": "ls"}]}))
    bad = client.put(f"/api/plans/{plan.id}", json={"steps": [{"id": "a", "type": "shell", "description": "", "command": "ls", "depends_on": ["zz"]}]})
    assert bad.status_code == 422
    ok = client.put(f"/api/plans/{plan.id}", json={"steps": [{"id": "a", "type": "shell", "description": "", "command": "pwd"}]})
    assert ok.json()["steps"][0]["command"] == "pwd" and ok.json()["id"] == plan.id
