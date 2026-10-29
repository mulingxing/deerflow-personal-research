"""Run a small real research task through the original FastAPI SSE endpoint.

This consumes DeepSeek tokens and Tavily credits. It exercises plan approval,
resume, research tools and report generation, without changing the workflow.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time
from uuid import uuid4

import httpx


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
TASK = (
    "为在 Windows 上学习 Python 的学生调研项目环境管理方案："
    "比较 Python venv + pip 与 uv 创建和管理独立项目环境的方式。"
    "必须联网查阅 docs.python.org 的 venv 官方文档和 docs.astral.sh 的 uv 官方文档，"
    "不要只凭已有知识回答。研究计划只安排 1 个 research 步骤，need_search=true。"
    "研究阶段最多搜索 2 次，只收集官方文档证据，不执行代码，不生成图片。"
    "最终用中文给出约 500 字的说明，包含选择建议、Windows PowerShell 命令和来源链接。"
)


def main() -> int:
    RUNTIME.mkdir(exist_ok=True)
    started = time.monotonic()
    summary = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "thread_id": "learning-" + uuid4().hex,
        "task": TASK,
        "checks": {},
        "http_statuses": [],
        "events": {},
        "agents": [],
        "tools": [],
        "search_results": [],
        "error_types": [],
    }
    counts = Counter()
    agents = []
    tools = {}
    results = []
    text = {}
    interrupted = False
    complete = False
    stream_error = False
    payload = {
        "thread_id": summary["thread_id"],
        "messages": [{"role": "user", "content": TASK}],
        "locale": "zh-CN",
        "max_plan_iterations": 1,
        "max_step_num": 1,
        "max_search_results": 2,
        "auto_accepted_plan": False,
        "enable_background_investigation": False,
        "enable_web_search": True,
        "enable_deep_thinking": False,
        "enable_clarification": False,
        "report_style": "popular_science",
    }

    def consume(kind, data):
        nonlocal interrupted, complete, stream_error
        counts[kind] += 1
        agent = data.get("agent", "")
        if agent and agent not in agents:
            agents.append(agent)
            print(f"[STAGE] {agent}", flush=True)
        if kind == "error":
            stream_error = True
            print("[FAIL] Server emitted an error event; provider text omitted.", flush=True)
        if kind == "interrupt":
            interrupted = True
            print("[PASS] Plan paused for human review.", flush=True)
        for call in data.get("tool_calls", []) + data.get("tool_call_chunks", []):
            if call.get("id") and call.get("name"):
                tools[call["id"]] = call["name"]
        content = data.get("content", "")
        if kind == "message_chunk" and isinstance(content, str):
            text[agent] = text.get(agent, "") + content
            if agent == "reporter" and data.get("finish_reason") == "stop":
                complete = True
        if kind == "tool_call_result":
            name = tools.get(data.get("tool_call_id"), "unknown")
            try:
                decoded = json.loads(content)
            except (TypeError, ValueError):
                decoded = None
            pages = [item for item in decoded if isinstance(item, dict) and item.get("type") == "page"] if isinstance(decoded, list) else []
            failed = (isinstance(decoded, dict) and bool(decoded.get("error"))) or (
                isinstance(content, str) and content.startswith("Failed to crawl.")
            )
            crawled = decoded.get("crawled_content", "") if isinstance(decoded, dict) else ""
            results.append({
                "name": name, "page_count": len(pages), "error": failed,
                "crawled_characters": len(crawled) if isinstance(crawled, str) else 0,
            })
            for page in pages:
                summary["search_results"].append({"title": page.get("title"), "url": page.get("url")})
            print(f"[TOOL] {name}; pages={len(pages)}; error={failed}", flush=True)

    def request(client, body):
        # Only local HTTP is permitted; the unmodified server calls providers.
        with client.stream("POST", "http://127.0.0.1:8000/api/chat/stream", json=body) as response:
            summary["http_statuses"].append(response.status_code)
            response.raise_for_status()
            event = "message"
            lines = []
            for line in response.iter_lines():
                if time.monotonic() - started > 300:
                    raise TimeoutError("Research verification exceeded five minutes")
                if not line:
                    if lines:
                        consume(event, json.loads("\n".join(lines)))
                    event, lines = "message", []
                elif line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    lines.append(line[5:].lstrip())
            if lines:
                consume(event, json.loads("\n".join(lines)))

    try:
        with httpx.Client(timeout=httpx.Timeout(100, connect=10), trust_env=False) as client:
            request(client, payload)
            summary["checks"]["plan_interrupt"] = interrupted and not stream_error
            summary["checks"]["no_research_before_approval"] = interrupted and not results and not text.get("reporter")
            if interrupted and not stream_error:
                (RUNTIME / "research-plan.txt").write_text(text.get("planner", ""), encoding="utf-8")
                print("[ACTION] Resume this test plan using the original accepted-feedback API.", flush=True)
                request(client, {**payload, "messages": [], "interrupt_feedback": "accepted"})
    except Exception as exc:
        summary["error_types"].append(type(exc).__name__)
        print(f"[FAIL] {type(exc).__name__}; sensitive exception text omitted.", flush=True)

    report = text.get("reporter", "")
    summary["checks"].update({
        "tool_selection": "web_search" in tools.values(),
        "search_results": bool(summary["search_results"]),
        "report_generated": len(report.strip()) > 200,
        "report_finished": complete,
        "report_has_links": bool(re.search(r"https?://[^\s)\]>]+", report)),
        "no_stream_error": not stream_error and not summary["error_types"],
        "no_tool_error": not any(item["error"] for item in results),
    })
    summary.update({
        "events": dict(counts), "agents": agents, "tools": list(tools.values()),
        "tool_results": results, "report_characters": len(report),
        "elapsed_seconds": round(time.monotonic() - started, 2),
    })
    summary["passed"] = all(summary["checks"].values())
    if report:
        (RUNTIME / "research-report.md").write_text(report, encoding="utf-8")
    (RUNTIME / "research-verification.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name, passed in summary["checks"].items():
        print(f"[{'PASS' if passed else 'FAIL'}] {name}", flush=True)
    print(f"Report length: {len(report)}; elapsed: {summary['elapsed_seconds']} seconds", flush=True)
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
