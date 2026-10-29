"""The reporter must receive only bounded sources from actual tool results."""

import json

from src.citations.report_sources import (
    MAX_EXCERPT_LENGTH,
    MAX_REPORT_SOURCES,
    build_report_source_context,
)


def test_report_source_context_preserves_local_page_and_excerpt():
    citations = [
        {
            "url": "qdrant://documents/paper#page=8",
            "title": "研究论文",
            "source_type": "local_document",
            "content_snippet": "方法 A。" * 300,
            "page_number": 8,
        }
    ]

    source = json.loads(build_report_source_context(citations))["sources"][0]

    assert source["source_id"] == 1
    assert source["page_number"] == 8
    assert source["source_type"] == "local_document"
    assert len(source["excerpt"]) == MAX_EXCERPT_LENGTH


def test_report_source_context_rejects_unsafe_urls_without_renumbering():
    citations = [
        {"url": "javascript:alert(1)", "title": "伪造链接"},
        {"url": "https://example.org/paper", "title": "网页来源"},
    ]

    sources = json.loads(build_report_source_context(citations))["sources"]

    assert len(sources) == 1
    assert sources[0]["source_id"] == 2


def test_report_source_context_caps_total_sources():
    citations = [
        {"url": f"https://example.org/{index}", "title": f"Source {index}"}
        for index in range(MAX_REPORT_SOURCES + 5)
    ]

    sources = json.loads(build_report_source_context(citations))["sources"]

    assert len(sources) == MAX_REPORT_SOURCES
    assert sources[-1]["source_id"] == MAX_REPORT_SOURCES
