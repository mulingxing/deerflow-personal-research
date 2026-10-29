"""Local conversation history API and restart behavior."""

from importlib import import_module
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.config.report_style import ReportStyle
from src.server.history import ConversationHistoryStore, ConversationInput


@pytest.fixture
def history_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    history = import_module("src.server.history")
    app_module = import_module("src.server.app")
    store = ConversationHistoryStore(tmp_path / "conversations.sqlite3")
    monkeypatch.setattr(history, "history_store", store)
    return TestClient(app_module.app), store, history


def test_create_list_read_delete_conversation(history_client):
    client, _store, _history = history_client
    conversation_id = "conversation_001"
    snapshot = {
        "messageIds": ["message-1"],
        "messages": [["message-1", {"role": "user", "content": "论文总结"}]],
        "researchCitations": [["research-1", [{"title": "资料", "page_number": 3}]]],
        "selectedResources": [{"uri": "qdrant://documents/file-1", "title": "论文"}],
    }

    saved = client.put(
        f"/api/conversations/{conversation_id}",
        json={"title": "论文总结", "status": "idle", "snapshot": snapshot},
    )
    assert saved.status_code == 200
    assert saved.json()["snapshot"] == snapshot

    listing = client.get("/api/conversations").json()["conversations"]
    assert [item["id"] for item in listing] == [conversation_id]
    assert "snapshot" not in listing[0]
    assert (
        client.get(f"/api/conversations/{conversation_id}").json()["snapshot"]
        == snapshot
    )

    deleted = client.delete(f"/api/conversations/{conversation_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/conversations/{conversation_id}").status_code == 404


def test_restart_marks_unfinished_run_for_retry(tmp_path: Path):
    database_path = tmp_path / "history.sqlite3"
    store = ConversationHistoryStore(database_path)
    store.save(
        "conversation_002",
        ConversationInput(
            title="正在研究", status="waiting_feedback", snapshot={"x": 1}
        ),
    )

    restarted = ConversationHistoryStore(database_path)
    # 兼容性检查只导入服务模块，不代表服务真正重启。
    assert restarted.get("conversation_002").status == "waiting_feedback"
    restarted.recover_interrupted()
    restored = restarted.get("conversation_002")

    assert restored is not None
    assert restored.status == "needs_retry"
    assert restored.snapshot == {"x": 1}


def test_conflicting_tab_cannot_overwrite_or_delete_newer_snapshot(history_client):
    client, _store, _history = history_client
    path = "/api/conversations/conversation_005"
    first = client.put(path, json={"title": "第一版", "snapshot": {"x": 1}})
    assert first.status_code == 200
    version = first.json()["updated_at"]

    second = client.put(
        path,
        json={
            "title": "第二版",
            "snapshot": {"x": 2},
            "expected_updated_at": version,
        },
    )
    assert second.status_code == 200
    assert second.json()["updated_at"] != version

    stale = client.put(
        path,
        json={
            "title": "旧标签页",
            "snapshot": {"x": 3},
            "expected_updated_at": version,
        },
    )
    assert stale.status_code == 409
    assert (
        client.delete(path, params={"expected_updated_at": version}).status_code == 409
    )
    assert client.get(path).json()["snapshot"] == {"x": 2}


def test_rejects_invalid_id_and_oversized_snapshot(history_client, monkeypatch):
    client, _store, history = history_client
    payload = {"title": "测试", "snapshot": {"text": "x" * 50}}
    assert client.put("/api/conversations/short", json=payload).status_code == 400

    monkeypatch.setattr(history, "MAX_SNAPSHOT_BYTES", 32)
    response = client.put("/api/conversations/conversation_003", json=payload)
    assert response.status_code == 413
    assert client.get("/api/conversations/conversation_003").status_code == 404


def test_history_methods_are_allowed_by_cors(history_client):
    client, _store, _history = history_client
    response = client.options(
        "/api/conversations/conversation_004",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "PUT",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


@pytest.mark.asyncio
async def test_previous_turns_do_not_become_current_clarification_history():
    app_module = import_module("src.server.app")
    captured = {}

    async def empty_stream(_graph, workflow_input, _config, _thread_id):
        captured["workflow_input"] = workflow_input
        if False:
            yield ""

    with patch.object(app_module, "_stream_graph_events", empty_stream):
        async for _event in app_module._astream_workflow_generator(
            messages=[{"role": "user", "content": "这次研究量子计算"}],
            thread_id="history-context-test",
            resources=[],
            max_plan_iterations=1,
            max_step_num=1,
            max_search_results=2,
            auto_accepted_plan=True,
            interrupt_feedback="",
            mcp_settings={},
            enable_background_investigation=False,
            enable_web_search=False,
            report_style=ReportStyle.ACADEMIC,
            enable_deep_thinking=False,
            enable_clarification=True,
            max_clarification_rounds=3,
            conversation_history=[
                {"role": "user", "content": "以前研究气候"},
                {"role": "assistant", "content": "气候报告"},
            ],
        ):
            pass

    workflow_input = captured["workflow_input"]
    assert workflow_input["research_topic"] == "这次研究量子计算"
    assert workflow_input["clarification_history"] == ["这次研究量子计算"]
    assert [item["role"] for item in workflow_input["messages"]] == [
        "assistant",
        "user",
    ]
    assert "以前研究气候" in workflow_input["messages"][0]["content"]
