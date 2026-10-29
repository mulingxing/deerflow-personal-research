"""Focused checks for uploaded document parsing and job status."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.rag.ingestion import CHUNK_SIZE, parse_document
from src.rag.upload_jobs import UploadJobStore


def test_markdown_keeps_headings_and_splits_long_text(tmp_path: Path):
    path = tmp_path / "notes.md"
    path.write_text(
        "# 第一章\n" + "知识点。" * 600 + "\n# 第二章\n示例", encoding="utf-8"
    )

    chunks = parse_document(path, path.name)

    assert {chunk["section"] for chunk in chunks} == {"第一章", "第二章"}
    assert all(0 < len(chunk["content"]) <= CHUNK_SIZE for chunk in chunks)
    assert any("示例" in chunk["content"] for chunk in chunks)


def test_pdf_keeps_page_numbers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    class FakeReader:
        is_encrypted = False

        def __init__(self, _source):
            self.pages = [
                SimpleNamespace(extract_text=lambda: "第一页内容"),
                SimpleNamespace(extract_text=lambda: "第二页内容"),
            ]

    monkeypatch.setitem(sys.modules, "pypdf", SimpleNamespace(PdfReader=FakeReader))
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"fake pdf")

    chunks = parse_document(path, path.name)

    assert [chunk["page_number"] for chunk in chunks] == [1, 2]
    assert chunks[1]["content"] == "第二页内容"


def test_real_pdf_text_is_extracted(tmp_path: Path):
    pypdf = pytest.importorskip("pypdf")
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    text_stream = DecodedStreamObject()
    text_stream.set_data(b"BT /F1 12 Tf 50 250 Td (Hello PDF) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(text_stream)
    path = tmp_path / "paper.pdf"
    writer.write(path)

    chunks = parse_document(path, path.name)

    assert chunks == [{"content": "Hello PDF", "page_number": 1}]


def test_scan_without_text_has_clear_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    class FakeReader:
        is_encrypted = False

        def __init__(self, _source):
            self.pages = [SimpleNamespace(extract_text=lambda: "")]

    monkeypatch.setitem(sys.modules, "pypdf", SimpleNamespace(PdfReader=FakeReader))
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"fake pdf")

    with pytest.raises(ValueError, match="OCR"):
        parse_document(path, path.name)


def test_docx_keeps_heading_and_table_text(tmp_path: Path):
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_heading("研究方法", level=1)
    document.add_paragraph("先检索论文。")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "概念"
    table.cell(0, 1).text = "解释"
    path = tmp_path / "research.docx"
    document.save(path)

    chunks = parse_document(path, path.name)

    assert len(chunks) == 1
    assert chunks[0]["section"] == "研究方法"
    assert "先检索论文" in chunks[0]["content"]
    assert "概念 | 解释" in chunks[0]["content"]


def test_job_store_marks_interrupted_import_after_restart(tmp_path: Path):
    database_path = tmp_path / "jobs.sqlite3"
    jobs = UploadJobStore(database_path)
    jobs.create("task-1", "paper.pdf")
    jobs.update("task-1", status="processing", progress=50)

    restarted_jobs = UploadJobStore(database_path)
    job = restarted_jobs.get("task-1")

    assert job is not None
    assert restarted_jobs.interrupted_task_ids == ["task-1"]
    assert job["status"] == "failed"
    assert "restart" in job["error"]
