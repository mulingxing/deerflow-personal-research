"""Upload job API without external embedding or vector services."""

from importlib import import_module
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.rag.retriever import Resource
from src.rag.upload_jobs import UploadJobStore


@pytest.fixture
def upload_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    app_module = import_module("src.server.app")
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    jobs = UploadJobStore(tmp_path / "jobs.sqlite3")
    calls = []

    class FakeRetriever:
        def ingest_file(self, content, filename, **kwargs):
            calls.append((content, filename, kwargs))
            return Resource(uri=f"test://{filename}", title=filename)

    monkeypatch.setattr(app_module, "build_retriever", lambda: FakeRetriever())
    monkeypatch.setattr(app_module, "rag_upload_jobs", jobs)
    monkeypatch.setattr(app_module, "RAG_UPLOAD_DIRECTORY", uploads)
    return TestClient(app_module.app), calls, uploads, app_module


def test_upload_job_indexes_markdown_and_reports_completion(upload_client):
    client, calls, uploads, _app_module = upload_client

    response = client.post(
        "/api/rag/upload/jobs",
        files={
            "file": ("notes.md", "# 学习笔记\n\n这是重点。".encode(), "text/markdown")
        },
    )

    assert response.status_code == 202
    task_id = response.json()["task_id"]
    status = client.get(f"/api/rag/upload/jobs/{task_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "completed"
    assert status.json()["progress"] == 100
    assert status.json()["resource"]["uri"] == "test://notes.md"
    assert calls[0][0] == b""
    assert calls[0][1] == "notes.md"
    assert calls[0][2]["chunks"][0]["section"] == "学习笔记"
    assert not list(uploads.iterdir())


def test_upload_job_rejects_oversized_file(upload_client, monkeypatch):
    client, calls, uploads, app_module = upload_client
    monkeypatch.setattr(app_module, "RAG_JOB_MAX_UPLOAD_SIZE_BYTES", 8)

    response = client.post(
        "/api/rag/upload/jobs",
        files={"file": ("notes.txt", b"123456789", "text/plain")},
    )

    assert response.status_code == 413
    assert not calls
    assert not list(uploads.iterdir())


def test_upload_job_accepts_multiple_read_blocks(upload_client):
    client, calls, _uploads, _app_module = upload_client
    large_text = b"a" * (2 * 1024 * 1024)

    response = client.post(
        "/api/rag/upload/jobs",
        files={"file": ("large.txt", large_text, "text/plain")},
    )

    assert response.status_code == 202
    task_id = response.json()["task_id"]
    assert client.get(f"/api/rag/upload/jobs/{task_id}").json()["status"] == "completed"
    assert len(calls[0][2]["chunks"]) > 1


def test_upload_job_reports_invalid_pdf(upload_client):
    client, calls, uploads, _app_module = upload_client

    response = client.post(
        "/api/rag/upload/jobs",
        files={"file": ("broken.pdf", b"not a pdf", "application/pdf")},
    )

    assert response.status_code == 202
    task_id = response.json()["task_id"]
    status = client.get(f"/api/rag/upload/jobs/{task_id}").json()
    assert status["status"] == "failed"
    assert "PDF" in status["error"]
    assert not calls
    assert not list(uploads.iterdir())


def test_upload_job_rejects_unknown_status(upload_client):
    client, *_ = upload_client

    response = client.get("/api/rag/upload/jobs/no-such-task")

    assert response.status_code == 404
