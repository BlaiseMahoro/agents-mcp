import pytest
from fastapi.testclient import TestClient

from agents_core import config
from agents_core.api import access
from agents_core.api.main import app
from agents_core.schemas import AgentEvent

ALICE = {"X-Visitor-Id": "alice-0000000000000001"}
BOB = {"X-Visitor-Id": "bob-00000000000000000002"}


@pytest.fixture(autouse=True)
def demo_mode(monkeypatch):
    path = config.config_path()
    path.write_text(path.read_text() + "\ndeployment:\n  demo: true\n  messages_per_visitor_hour: 2\n  messages_per_day: 3\n")
    config.get_config.cache_clear()
    monkeypatch.setenv("ADMIN_TOKEN", "s3cret-token")
    monkeypatch.setattr(access, "limiter", access.RateLimiter())

    async def fake_turn(conv_id, content, mode):
        yield AgentEvent.text("orchestrator", "hi")

    monkeypatch.setattr("agents_core.api.main.handle_turn", fake_turn)


client = TestClient(app)


def test_visitor_header_required():
    assert client.get("/api/conversations").status_code == 400


def test_chats_are_private_per_visitor():
    conv = client.post("/api/conversations", headers=ALICE).json()
    assert "owner" not in conv
    assert [c["id"] for c in client.get("/api/conversations", headers=ALICE).json()] == [conv["id"]]
    assert client.get("/api/conversations", headers=BOB).json() == []
    assert client.get(f"/api/conversations/{conv['id']}", headers=BOB).status_code == 404
    assert client.delete(f"/api/conversations/{conv['id']}", headers=BOB).status_code == 404


def test_execute_locked_off_even_if_saved_on():
    s = client.put("/api/settings", json={"enabled": {"execute": True}}, headers={"X-Admin-Token": "s3cret-token"}).json()
    assert s["enabled"]["execute"] is False


def test_settings_need_admin_token():
    assert client.get("/api/settings").json()["can_edit"] is False
    assert client.put("/api/settings", json={"enabled": {"research": False}}).status_code == 403
    assert client.put("/api/settings", json={"enabled": {"research": False}}, headers={"X-Admin-Token": "wrong"}).status_code == 403
    assert client.get("/api/settings", headers={"X-Admin-Token": "s3cret-token"}).json()["can_edit"] is True


def test_health_hides_details_from_visitors(monkeypatch):
    r = client.get("/api/health").json()
    assert all(v["detail"] == "" for k, v in r.items() if k != "providers")


def test_rate_limits():
    conv = client.post("/api/conversations", headers=ALICE).json()["id"]
    send = lambda h, c: client.post(f"/api/conversations/{c}/messages", json={"content": "x"}, headers=h).status_code
    assert send(ALICE, conv) == 200
    assert send(ALICE, conv) == 200
    assert send(ALICE, conv) == 429  # 2 per visitor per hour
    bob_conv = client.post("/api/conversations", headers=BOB).json()["id"]
    assert send(BOB, bob_conv) == 200  # same IP as Alice, but the IP allowance is 3x
    assert send(BOB, bob_conv) == 429  # daily total of 3 reached
