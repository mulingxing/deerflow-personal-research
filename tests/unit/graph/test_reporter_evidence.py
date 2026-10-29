"""Check that the final report receives real, bounded source evidence."""

import json
from types import SimpleNamespace

from langchain_core.messages import SystemMessage

from src.graph import nodes


class _PassThroughContext:
    def __init__(self, _token_limit):
        pass

    def compress_messages(self, state):
        return state


class _RecordingLLM:
    def __init__(self):
        self.messages = []

    def invoke(self, messages):
        self.messages = messages
        return SimpleNamespace(content="# 研究报告\n\n结论。[[1]](#ref-1)")


def test_reporter_receives_local_page_and_safe_source_ids(monkeypatch):
    llm = _RecordingLLM()
    monkeypatch.setattr(nodes, "ContextManager", _PassThroughContext)
    monkeypatch.setattr(nodes, "get_llm_token_limit_by_type", lambda _name: 10000)
    monkeypatch.setattr(nodes, "get_llm_by_type", lambda _name: llm)
    monkeypatch.setattr(
        nodes,
        "apply_prompt_template",
        lambda *_args, **_kwargs: [SystemMessage(content="Write a report")],
    )
    monkeypatch.setattr(
        nodes.Configuration,
        "from_runnable_config",
        classmethod(lambda _cls, _config: object()),
    )
    citations = [
        {
            "url": "qdrant://documents/paper#page=3",
            "title": "论文",
            "content_snippet": "研究采用访谈法。",
            "page_number": 3,
            "source_type": "local_document",
        }
    ]

    result = nodes.reporter_node(
        {
            "current_plan": SimpleNamespace(title="研究题目", thought="解释方法"),
            "locale": "zh-CN",
            "observations": ["研究观察"],
            "citations": citations,
        },
        {},
    )

    evidence = next(msg for msg in llm.messages if msg.name == "source_evidence")
    source = json.loads(evidence.content)["sources"][0]
    assert source["source_id"] == 1
    assert source["page_number"] == 3
    assert source["excerpt"] == "研究采用访谈法。"
    assert result["citations"] == citations
    assert "[[1]](#ref-1)" in result["final_report"]
