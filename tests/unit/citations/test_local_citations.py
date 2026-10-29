from langchain_core.messages import ToolMessage

from src.citations.extractor import extract_citations_from_messages


def test_local_search_citation_keeps_page_and_source_type():
    message = ToolMessage(
        name="local_search_tool",
        tool_call_id="local-search",
        content=(
            '[{"id":"paper","url":"qdrant://documents/paper.pdf",'
            '"title":"paper.pdf","chunks":[{"content":"论文方法说明",'
            '"similarity":0.9,"page_number":3,"section":"方法"}]}]'
        ),
    )

    citations = extract_citations_from_messages([message])

    assert len(citations) == 1
    assert citations[0]["source_type"] == "local_document"
    assert citations[0]["page_number"] == 3
    assert citations[0]["url"] == "qdrant://documents/paper.pdf#page=3"
