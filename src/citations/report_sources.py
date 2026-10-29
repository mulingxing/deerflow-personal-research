"""Prepare bounded, source-aware evidence for the final report writer."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

MAX_REPORT_SOURCES = 24
MAX_TITLE_LENGTH = 160
MAX_EXCERPT_LENGTH = 400
ALLOWED_SOURCE_SCHEMES = {
    "http",
    "https",
    "rag",
    "qdrant",
    "milvus",
    "ragflow",
    "dify",
    "moi",
    "vikingdb",
}


def _one_line(value: Any, limit: int) -> str:
    """Keep tool output readable and limit the context sent to the model."""
    return " ".join(str(value or "").split())[:limit]


def build_report_source_context(citations: list[dict[str, Any]]) -> str:
    """Build a numbered JSON source list without inventing missing evidence."""
    sources: list[dict[str, Any]] = []
    for number, citation in enumerate(citations[:MAX_REPORT_SOURCES], start=1):
        if not isinstance(citation, dict):
            continue
        url = str(citation.get("url") or "").strip()
        if urlsplit(url).scheme.lower() not in ALLOWED_SOURCE_SCHEMES:
            continue

        # 上传的资料和网页内容都属于不可信输入，只作为引用数据交给模型。
        source = {
            "source_id": number,
            "title": _one_line(citation.get("title"), MAX_TITLE_LENGTH),
            "url": url,
            "source_type": _one_line(citation.get("source_type"), 40),
            "excerpt": _one_line(
                citation.get("content_snippet") or citation.get("description"),
                MAX_EXCERPT_LENGTH,
            ),
        }
        if citation.get("page_number"):
            source["page_number"] = citation["page_number"]
        if citation.get("section"):
            source["section"] = _one_line(citation["section"], MAX_TITLE_LENGTH)
        sources.append(source)

    return json.dumps({"sources": sources}, ensure_ascii=False)
