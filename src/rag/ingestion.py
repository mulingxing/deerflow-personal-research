"""Parse uploaded learning materials into bounded, source-aware text chunks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.config.loader import get_int_env

CHUNK_SIZE = 1800
CHUNK_OVERLAP = 180
MAX_CHUNKS = max(1, get_int_env("RAG_MAX_CHUNKS", 5000))


def _split_text(text: str) -> list[str]:
    """Keep individual chunks small enough for embedding and retrieval."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", "。", "！", "？", "；", " ", ""],
    )
    return [chunk.strip() for chunk in splitter.split_text(text) if chunk.strip()]


def _append_chunks(
    target: list[dict[str, Any]], text: str, **source: str | int
) -> None:
    for chunk in _split_text(text):
        if len(target) >= MAX_CHUNKS:
            raise ValueError("Document is too long for one import job")
        target.append({"content": chunk, **source})


def _parse_plain_text(path: Path, filename: str) -> list[dict[str, Any]]:
    try:
        content = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Text files must use UTF-8 encoding") from exc

    chunks: list[dict[str, Any]] = []
    section = filename
    section_lines: list[str] = []

    def flush_section() -> None:
        _append_chunks(chunks, "\n".join(section_lines), section=section)
        section_lines.clear()

    for line in content.splitlines():
        # 中文注释：Markdown 标题作为来源位置保留，便于以后定位笔记章节。
        if filename.lower().endswith(".md") and line.lstrip().startswith("#"):
            heading = line.lstrip().lstrip("#").strip()
            if heading:
                flush_section()
                section = heading
                continue
        section_lines.append(line)
    flush_section()
    return chunks


def _parse_pdf(path: Path) -> list[dict[str, Any]]:
    from pypdf import PdfReader

    chunks: list[dict[str, Any]] = []
    try:
        with path.open("rb") as source:
            reader = PdfReader(source)
            if reader.is_encrypted and not reader.decrypt(""):
                raise ValueError("Password-protected PDFs are not supported")

            for page_number, page in enumerate(reader.pages, start=1):
                # 中文注释：每页单独切块，避免检索结果跨页后失去页码。
                _append_chunks(
                    chunks, page.extract_text() or "", page_number=page_number
                )
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Cannot read this PDF file") from exc
    return chunks


def _parse_docx(path: Path) -> list[dict[str, Any]]:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document = Document(path)
    except Exception as exc:
        raise ValueError("Cannot read this Word document") from exc

    chunks: list[dict[str, Any]] = []
    section = "正文"
    section_lines: list[str] = []

    def flush_section() -> None:
        _append_chunks(chunks, "\n".join(section_lines), section=section)
        section_lines.clear()

    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            paragraph = Paragraph(child, document)
            text = paragraph.text.strip()
            if not text:
                continue
            style_id = (paragraph.style.style_id or "").lower()
            style_name = (paragraph.style.name or "").lower()
            if style_id.startswith("heading") or style_name.startswith("标题"):
                flush_section()
                section = text
            else:
                section_lines.append(text)
        elif child.tag == qn("w:tbl"):
            table = Table(child, document)
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    section_lines.append(" | ".join(cells))

    flush_section()
    return chunks


def parse_document(path: Path, filename: str) -> list[dict[str, Any]]:
    """Extract text while retaining PDF pages or document section titles."""
    extension = path.suffix.lower()
    if extension in {".md", ".txt"}:
        chunks = _parse_plain_text(path, filename)
    elif extension == ".pdf":
        chunks = _parse_pdf(path)
    elif extension == ".docx":
        chunks = _parse_docx(path)
    else:
        raise ValueError("Unsupported document type")

    if not chunks:
        raise ValueError(
            "No extractable text found. Scanned PDFs require OCR before upload."
        )
    return chunks
