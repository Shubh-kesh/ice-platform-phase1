"""
AI-1.2 — assistant HTTP surface tests: SSE contract, capabilities, auth,
disabled behavior, and rate limiting. Uses the ASGI test client + a fake model
(no OpenAI key, no network).
"""
import json

import pytest
from langchain_core.messages import AIMessage

import app.api.v1.assistant as assistant_mod
from app.core.config import settings
from tests.conftest import assign_user_to_project, auth_header
from tests.fakes import FakeChatModel

pytestmark = pytest.mark.filterwarnings("ignore:Pydantic serializer warnings")


def parse_sse(text: str):
    """Parse SSE frames into [(event, data_dict), ...]."""
    frames = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        event, data = None, None
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = json.loads(line[len("data:"):].strip())
        if event and data is not None:
            frames.append((event, data))
    return frames


async def _enable_assistant(monkeypatch, fake_factory):
    monkeypatch.setattr(settings, "ICE_AI_ENABLED", True)
    monkeypatch.setattr(settings, "ICE_AI_API_KEY", "sk-test")
    monkeypatch.setattr(assistant_mod, "build_model", fake_factory)


# --- SSE contract -------------------------------------------------------------


async def test_chat_sse_contract(client, test_admin_user, test_project, monkeypatch):
    def fake_factory():
        return FakeChatModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "get_project_health",
                            "args": {"project_id": str(test_project.id)},
                            "id": "call-1",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="The project is on track."),
            ]
        )

    await _enable_assistant(monkeypatch, fake_factory)
    header = await auth_header(client, "admin@test.com")
    resp = await client.post(
        "/api/v1/assistant/chat",
        headers={"Authorization": header},
        json={"message": "why is this project unhealthy?"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    frames = parse_sse(resp.text)
    assert frames[0][0] == "assistant_start"
    assert frames[-1][0] == "assistant_complete"
    assert "error" not in [e for e, _ in frames]

    (start,) = [d for e, d in frames if e == "assistant_start"]
    (complete,) = [d for e, d in frames if e == "assistant_complete"]
    assert start["read_only"] is True
    assert start["request_id"] == complete["request_id"]  # stable across events

    text = "".join(d["text"] for e, d in frames if e == "assistant_token")
    assert text == "The project is on track."

    started = [d for e, d in frames if e == "tool_started"]
    assert started == [{"tool": "Project health"}]
    assert [d for e, d in frames if e == "tool_finished"] == [
        {"tool": "Project health", "ok": True}
    ]

    # usage shape is safe and complete-ish
    assert set(complete["usage"]) >= {
        "model_calls", "tool_calls", "input_tokens", "output_tokens", "total_tokens"
    }
    assert complete["usage"]["model_calls"] == 2
    assert complete["usage"]["tool_calls"] == 1
    assert isinstance(complete["took_ms"], int)

    # no internal names/args in any event payload
    blob = json.dumps(frames)
    assert "get_project_health" not in blob
    assert "project_id" not in blob


# --- Auth / disabled ----------------------------------------------------------


async def test_chat_requires_auth(client, test_admin_user, monkeypatch):
    await _enable_assistant(monkeypatch, lambda: FakeChatModel())
    resp = await client.post("/api/v1/assistant/chat", json={"message": "hi"})
    assert resp.status_code == 401


async def test_chat_disabled_returns_503(client, test_admin_user, monkeypatch):
    monkeypatch.setattr(settings, "ICE_AI_ENABLED", False)
    monkeypatch.setattr(settings, "ICE_AI_API_KEY", "")
    header = await auth_header(client, "admin@test.com")
    resp = await client.post(
        "/api/v1/assistant/chat",
        headers={"Authorization": header},
        json={"message": "hi"},
    )
    assert resp.status_code == 503


async def test_chat_rejects_empty_message(client, test_admin_user, monkeypatch):
    await _enable_assistant(monkeypatch, lambda: FakeChatModel())
    header = await auth_header(client, "admin@test.com")
    resp = await client.post(
        "/api/v1/assistant/chat", headers={"Authorization": header}, json={"message": "   "}
    )
    assert resp.status_code in (422, 400)


# --- Capabilities --------------------------------------------------------------


async def test_capabilities_requires_auth(client):
    resp = await client.get("/api/v1/assistant/capabilities")
    assert resp.status_code == 401


async def test_capabilities_role_scoped(client, test_admin_user, test_client_user, test_db, test_project, monkeypatch):
    await _enable_assistant(monkeypatch, lambda: FakeChatModel())
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)

    admin_header = await auth_header(client, "admin@test.com")
    admin = (await client.get("/api/v1/assistant/capabilities", headers={"Authorization": admin_header})).json()
    assert admin["read_only"] is True
    # W7.1: conversation memory is ON (process-local InMemorySaver) by default.
    assert admin["memory_enabled"] is True
    assert admin["memory_mode"] in ("saver", "summarize", "context_edit")
    assert admin["web_search_enabled"] is False
    assert admin["mutations_enabled"] is False
    admin_labels = {t["label"] for t in admin["tools"]}
    assert "Project budget" in admin_labels and "Project health" in admin_labels

    client_header = await auth_header(client, "client@test.com")
    client_caps = (await client.get("/api/v1/assistant/capabilities", headers={"Authorization": client_header})).json()
    client_labels = {t["label"] for t in client_caps["tools"]}
    assert "Project budget" not in client_labels
    assert "Purchase orders" not in client_labels
    assert "Projects" in client_labels and "Notifications" in client_labels


# --- Rate limiting --------------------------------------------------------------


async def test_chat_rate_limited(client, test_admin_user, test_project, monkeypatch):
    """The assistant endpoint is wired to ASSISTANT_RATE_LIMIT (10/min/IP).

    The `client` fixture disables the limiter by default; re-enable it for this
    one test (repo convention, see test_auth.py). A 11th request within the
    minute window is rejected with 429.
    """
    await _enable_assistant(monkeypatch, lambda: FakeChatModel())
    header = await auth_header(client, "admin@test.com")

    from app.main import app

    app.state.limiter.enabled = True
    try:
        responses = [
            await client.post(
                "/api/v1/assistant/chat",
                headers={"Authorization": header},
                json={"message": "list my projects"},
            )
            for _ in range(11)
        ]
    finally:
        app.state.limiter.enabled = False

    assert responses[0].status_code == 200
    assert responses[10].status_code == 429
