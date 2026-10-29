# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

import pytest

import src.rag.qdrant as qdrant_mod
from src.rag.qdrant import QdrantProvider


class DummyEmbedding:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def embed_query(self, text: str):
        return [0.1] * 1536

    def embed_documents(self, texts):
        return [[0.1] * 1536 for _ in texts]


@pytest.fixture(autouse=True)
def patch_embeddings(monkeypatch):
    monkeypatch.setenv("QDRANT_EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("QDRANT_EMBEDDING_MODEL", "text-embedding-ada-002")
    monkeypatch.setenv("QDRANT_COLLECTION", "documents")
    monkeypatch.setenv("QDRANT_LOCATION", ":memory:")
    monkeypatch.setattr(qdrant_mod, "OpenAIEmbeddings", DummyEmbedding)
    monkeypatch.setattr(qdrant_mod, "DashscopeEmbeddings", DummyEmbedding)
    yield


@pytest.fixture
def project_root():
    return Path(qdrant_mod.__file__).parent.parent.parent


@pytest.fixture
def temp_examples_dir(project_root):
    temp_dir_name = f"examples_test_{uuid4().hex}"
    temp_dir_path = project_root / temp_dir_name
    temp_dir_path.mkdir(parents=True, exist_ok=True)
    yield temp_dir_path
    if temp_dir_path.exists():
        shutil.rmtree(temp_dir_path)


@pytest.fixture
def temp_error_examples_dir(project_root):
    temp_dir_name = f"examples_error_{uuid4().hex}"
    temp_dir_path = project_root / temp_dir_name
    temp_dir_path.mkdir(parents=True, exist_ok=True)
    yield temp_dir_path
    if temp_dir_path.exists():
        shutil.rmtree(temp_dir_path)


@pytest.fixture
def temp_load_skip_examples_dir(project_root):
    temp_dir_name = f"examples_load_skip_{uuid4().hex}"
    temp_dir_path = project_root / temp_dir_name
    temp_dir_path.mkdir(parents=True, exist_ok=True)
    yield temp_dir_path
    if temp_dir_path.exists():
        shutil.rmtree(temp_dir_path)


def test_init_openai_provider(monkeypatch):
    monkeypatch.setenv("QDRANT_EMBEDDING_PROVIDER", "openai")
    provider = QdrantProvider()
    assert provider.embedding_provider == "openai"
    assert isinstance(provider.embedding_model, DummyEmbedding)


def test_init_dashscope_provider(monkeypatch):
    monkeypatch.setenv("QDRANT_EMBEDDING_PROVIDER", "dashscope")
    provider = QdrantProvider()
    assert provider.embedding_provider == "dashscope"
    assert isinstance(provider.embedding_model, DummyEmbedding)


def test_init_invalid_provider(monkeypatch):
    monkeypatch.setenv("QDRANT_EMBEDDING_PROVIDER", "invalid_provider")
    with pytest.raises(ValueError, match="Unsupported embedding provider"):
        QdrantProvider()


def test_list_resources_reports_connection_error(monkeypatch):
    provider = QdrantProvider()

    def fail_to_connect():
        raise RuntimeError("Qdrant directory is locked")

    monkeypatch.setattr(provider, "_connect", fail_to_connect)
    with pytest.raises(RuntimeError, match="locked"):
        provider.list_resources()


def test_get_embedding_dimension_explicit(monkeypatch):
    monkeypatch.setenv("QDRANT_EMBEDDING_DIM", "2048")
    provider = QdrantProvider()
    assert provider.embedding_dim == 2048


def test_get_embedding_dimension_default(monkeypatch):
    monkeypatch.delenv("QDRANT_EMBEDDING_DIM", raising=False)
    monkeypatch.setenv("QDRANT_EMBEDDING_MODEL", "text-embedding-ada-002")
    provider = QdrantProvider()
    assert provider.embedding_dim == 1536


def test_get_embedding_dimension_unknown_model(monkeypatch):
    monkeypatch.delenv("QDRANT_EMBEDDING_DIM", raising=False)
    monkeypatch.setenv("QDRANT_EMBEDDING_MODEL", "unknown-model")
    provider = QdrantProvider()
    assert provider.embedding_dim == 1536


def test_connect_memory_mode(monkeypatch):
    monkeypatch.setenv("QDRANT_LOCATION", ":memory:")
    provider = QdrantProvider()
    provider._connect()
    assert provider.client is not None


def test_create_collection(monkeypatch):
    provider = QdrantProvider()
    provider.create_collection()
    assert provider.client is not None


def test_extract_title_from_markdown():
    provider = QdrantProvider()
    content = "# Test Title\n\nSome content"
    title = provider._extract_title_from_markdown(content, "test.md")
    assert title == "Test Title"


def test_extract_title_fallback():
    provider = QdrantProvider()
    content = "No title here"
    title = provider._extract_title_from_markdown(content, "test_file.md")
    assert title == "Test File"


def test_split_content_short():
    provider = QdrantProvider()
    content = "Short content"
    chunks = provider._split_content(content)
    assert len(chunks) == 1
    assert chunks[0] == content


def test_split_content_long(monkeypatch):
    monkeypatch.setenv("QDRANT_CHUNK_SIZE", "20")
    provider = QdrantProvider()
    content = (
        "Paragraph one here\n\nParagraph two here\n\n"
        "Paragraph three here\n\nParagraph four here"
    )
    chunks = provider._split_content(content)
    assert len(chunks) > 1


def test_string_to_uuid():
    provider = QdrantProvider()
    uuid1 = provider._string_to_uuid("test")
    uuid2 = provider._string_to_uuid("test")
    assert uuid1 == uuid2


def test_get_embedding():
    provider = QdrantProvider()
    embedding = provider._get_embedding("test text")
    assert len(embedding) == 1536
    assert all(isinstance(x, float) for x in embedding)


def test_load_examples_no_directory(monkeypatch, project_root):
    monkeypatch.setenv("QDRANT_EXAMPLES_DIR", "nonexistent_dir")
    provider = QdrantProvider()
    provider.load_examples()


def test_load_examples_empty_directory(monkeypatch, temp_examples_dir):
    monkeypatch.setenv("QDRANT_EXAMPLES_DIR", temp_examples_dir.name)
    provider = QdrantProvider()
    provider.load_examples()


def test_load_examples_with_files(monkeypatch, temp_examples_dir):
    monkeypatch.setenv("QDRANT_EXAMPLES_DIR", temp_examples_dir.name)

    md_file = temp_examples_dir / "test.md"
    md_file.write_text("# Test\n\nContent", encoding="utf-8")

    provider = QdrantProvider()
    provider.load_examples()

    loaded = provider.get_loaded_examples()
    assert len(loaded) == 1
    assert loaded[0]["title"] == "Test"


def test_load_examples_skip_existing(monkeypatch, temp_load_skip_examples_dir):
    monkeypatch.setenv("QDRANT_EXAMPLES_DIR", temp_load_skip_examples_dir.name)

    md_file = temp_load_skip_examples_dir / "test.md"
    md_file.write_text("# Test\n\nContent", encoding="utf-8")

    provider = QdrantProvider()
    provider.load_examples()
    provider.load_examples()

    loaded = provider.get_loaded_examples()
    assert len(loaded) == 1


def test_load_examples_force_reload(monkeypatch, temp_examples_dir):
    monkeypatch.setenv("QDRANT_EXAMPLES_DIR", temp_examples_dir.name)

    md_file = temp_examples_dir / "test.md"
    md_file.write_text("# Test\n\nContent", encoding="utf-8")

    provider = QdrantProvider()
    provider.load_examples()
    provider.load_examples(force_reload=True)

    loaded = provider.get_loaded_examples()
    assert len(loaded) == 1


def test_load_examples_error_handling(monkeypatch, temp_error_examples_dir):
    monkeypatch.setenv("QDRANT_EXAMPLES_DIR", temp_error_examples_dir.name)

    good_file = temp_error_examples_dir / "good.md"
    good_file.write_text("# Good\n\nContent", encoding="utf-8")

    bad_file = temp_error_examples_dir / "bad.md"
    bad_file.write_text("# Bad\n\n", encoding="utf-8")

    provider = QdrantProvider()
    provider.load_examples()

    loaded = provider.get_loaded_examples()
    assert len(loaded) >= 1


def test_list_resources_no_query(monkeypatch, temp_examples_dir):
    monkeypatch.setenv("QDRANT_EXAMPLES_DIR", temp_examples_dir.name)

    md_file = temp_examples_dir / "test.md"
    md_file.write_text("# Test\n\nContent", encoding="utf-8")

    provider = QdrantProvider()
    provider.load_examples()

    resources = provider.list_resources()
    assert len(resources) >= 1


def test_list_resources_with_query(monkeypatch, temp_examples_dir):
    monkeypatch.setenv("QDRANT_EXAMPLES_DIR", temp_examples_dir.name)

    md_file = temp_examples_dir / "test.md"
    md_file.write_text("# Test\n\nContent", encoding="utf-8")

    provider = QdrantProvider()
    provider.load_examples()

    resources = provider.list_resources(query="test")
    assert isinstance(resources, list)


def test_query_relevant_documents(monkeypatch, temp_examples_dir):
    monkeypatch.setenv("QDRANT_EXAMPLES_DIR", temp_examples_dir.name)

    md_file = temp_examples_dir / "test.md"
    md_file.write_text("# Test\n\nContent about testing", encoding="utf-8")

    provider = QdrantProvider()
    provider.load_examples()

    documents = provider.query_relevant_documents("testing")
    assert isinstance(documents, list)


def test_query_relevant_documents_with_resources(monkeypatch, temp_examples_dir):
    monkeypatch.setenv("QDRANT_EXAMPLES_DIR", temp_examples_dir.name)

    md_file = temp_examples_dir / "test.md"
    md_file.write_text("# Test\n\nContent", encoding="utf-8")

    provider = QdrantProvider()
    provider.load_examples()

    resources = provider.list_resources()
    documents = provider.query_relevant_documents("test", resources=resources)
    assert isinstance(documents, list)


def test_close():
    provider = QdrantProvider()
    provider._connect()
    provider.close()
    assert provider.client is None


def test_del():
    provider = QdrantProvider()
    provider._connect()
    del provider


def test_top_k_configuration(monkeypatch):
    monkeypatch.setenv("QDRANT_TOP_K", "20")
    provider = QdrantProvider()
    assert provider.top_k == 20


def test_top_k_invalid(monkeypatch):
    monkeypatch.setenv("QDRANT_TOP_K", "invalid")
    provider = QdrantProvider()
    assert provider.top_k == 10


def test_chunk_size_configuration(monkeypatch):
    monkeypatch.setenv("QDRANT_CHUNK_SIZE", "5000")
    provider = QdrantProvider()
    assert provider.chunk_size == 5000


def test_upload_lists_and_searches_selected_file_with_page_metadata(monkeypatch):
    monkeypatch.setenv("QDRANT_TOP_K", "1")
    provider = QdrantProvider()
    first = provider.ingest_file(b"First document", "first.txt")
    selected = provider.ingest_file(
        "第二份资料".encode("utf-8"),
        "second.pdf",
        chunks=[{"content": "第二份资料", "page_number": 3, "section": "结论"}],
    )

    assert {resource.uri for resource in provider.list_resources()} == {
        first.uri,
        selected.uri,
    }
    assert [resource.uri for resource in provider.list_resources("second")] == [
        selected.uri
    ]
    assert selected.filename == "second.pdf"
    assert provider.list_resources("second")[0].filename == "second.pdf"

    documents = provider.query_relevant_documents("资料", resources=[selected])
    assert len(documents) == 1
    assert documents[0].url == selected.uri
    assert documents[0].chunks[0].page_number == 3
    assert documents[0].chunks[0].section == "结论"


def test_list_resources_distinguishes_same_title_by_original_filename():
    provider = QdrantProvider()
    pdf = provider.ingest_file(b"PDF content", "Agent面试问答.pdf")
    word = provider.ingest_file(b"Word content", "Agent面试问答.docx")

    listed = {resource.filename: resource for resource in provider.list_resources()}
    assert listed["Agent面试问答.pdf"].uri == pdf.uri
    assert listed["Agent面试问答.docx"].uri == word.uri
    assert listed["Agent面试问答.pdf"].title == listed["Agent面试问答.docx"].title


def test_local_qdrant_directory_survives_provider_restart(monkeypatch, tmp_path):
    monkeypatch.setenv("QDRANT_LOCATION", str(tmp_path / "qdrant"))
    provider = QdrantProvider()
    uploaded = provider.ingest_file(b"Personal notes", "notes.txt")
    provider.close()

    restarted = QdrantProvider()
    try:
        assert uploaded.uri in {item.uri for item in restarted.list_resources()}
    finally:
        restarted.close()


def test_relative_qdrant_location_uses_project_root(monkeypatch, tmp_path):
    fake_module = tmp_path / "project" / "src" / "rag" / "qdrant.py"
    monkeypatch.setattr(qdrant_mod, "__file__", str(fake_module))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("QDRANT_LOCATION", "data/qdrant")

    provider = QdrantProvider()
    try:
        provider.create_collection()
        assert (tmp_path / "project" / "data" / "qdrant").is_dir()
        assert not (tmp_path / "data" / "qdrant").exists()
    finally:
        provider.close()


def test_upload_batches_embeddings_and_reports_progress():
    provider = QdrantProvider()
    calls = []
    progress = []

    def embed_documents(texts):
        calls.append(len(texts))
        return [[0.1] * provider.embedding_dim for _ in texts]

    provider.embedding_model.embed_documents = embed_documents
    uploaded = provider.ingest_file(
        b"",
        "large.pdf",
        chunks=[{"content": f"Content {index}"} for index in range(33)],
        progress_callback=lambda done, total: progress.append((done, total)),
    )

    assert uploaded.uri in {item.uri for item in provider.list_resources()}
    assert calls == [32, 1]
    assert progress == [(32, 33), (33, 33)]


def test_fastembed_configuration_is_lazy(monkeypatch):
    monkeypatch.setenv("QDRANT_EMBEDDING_PROVIDER", "fastembed")
    monkeypatch.delenv("QDRANT_EMBEDDING_MODEL", raising=False)
    provider = QdrantProvider()
    assert provider.embedding_model_name == "BAAI/bge-small-zh-v1.5"
    assert provider.embedding_dim == 512
    assert isinstance(provider.embedding_model, qdrant_mod.FastEmbedEmbeddings)
    monkeypatch.setattr(
        provider.embedding_model,
        "_load_model",
        lambda: pytest.fail("Listing resources must not load FastEmbed"),
    )
    assert provider.list_resources() == []


def test_collection_name_configuration(monkeypatch):
    monkeypatch.setenv("QDRANT_COLLECTION", "custom_collection")
    provider = QdrantProvider()
    assert provider.collection_name == "custom_collection"


def test_auto_load_examples_configuration(monkeypatch):
    monkeypatch.setenv("QDRANT_AUTO_LOAD_EXAMPLES", "false")
    provider = QdrantProvider()
    assert provider.auto_load_examples is False
