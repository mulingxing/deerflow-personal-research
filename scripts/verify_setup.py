r"""Verify this checkout without paid model requests unless --live is explicit.

Run with .venv\Scripts\python.exe scripts\verify_setup.py after starting the app.
Use --offline before starting services. Reports contain no keys or model output.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import logging
import os
from pathlib import Path
import sys
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / ".runtime" / "verification.json"


def has_deepseek_key() -> bool:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    return bool(key) and key.lower() not in {
        "xxx", "xxxx", "your_api_key", "your_deepseek_api_key", "sk-xxx",
    }


class Verification:
    def __init__(self, mode: str):
        self.started = time.perf_counter()
        self.report: dict[str, Any] = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "remote_model_requests": 0,
            "checks": [],
        }

    def add(self, name: str, status: str, detail: str, **metrics: Any) -> None:
        self.report["checks"].append(
            {"name": name, "status": status, "detail": detail, **metrics}
        )
        print(f"[{status}] {name}: {detail}", flush=True)

    def finish(self) -> int:
        counts = {
            status: sum(c["status"] == status for c in self.report["checks"])
            for status in ("PASS", "WARN", "FAIL")
        }
        self.report["summary"] = counts
        self.report["elapsed_seconds"] = round(time.perf_counter() - self.started, 3)
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(
            json.dumps(self.report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            f"\nPASS={counts['PASS']} WARN={counts['WARN']} FAIL={counts['FAIL']}"
            f"; remote model requests={self.report['remote_model_requests']}",
            flush=True,
        )
        print(f"Report: {REPORT_PATH}", flush=True)
        return 1 if counts["FAIL"] else 0


def load_project_environment(check: Verification) -> bool:
    """Use this checkout's credentials, not values inherited from another app."""
    try:
        from dotenv import load_dotenv

        for name in list(os.environ):
            if name.startswith(
                ("BASIC_MODEL__", "REASONING_MODEL__", "CODE_MODEL__", "VISION_MODEL__")
            ) or name in {"DEEPSEEK_API_KEY", "OPENAI_API_KEY"}:
                del os.environ[name]
        env_path = ROOT / ".env"
        if not env_path.is_file():
            check.add("project_environment", "FAIL", "Root .env is missing.")
            return False
        load_dotenv(env_path, override=True)
        # Verification must not send prompts or traces to another service.
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ["LANGCHAIN_TRACING"] = "false"
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        os.environ["LANGCHAIN_VERBOSE"] = "false"
        os.environ["LANGCHAIN_DEBUG"] = "false"
        os.environ["DEBUG"] = "False"
        # Server imports must never auto-ingest examples into a configured RAG DB.
        os.environ["MILVUS_AUTO_LOAD_EXAMPLES"] = "false"
        os.environ["QDRANT_AUTO_LOAD_EXAMPLES"] = "false"
        logging.disable(logging.CRITICAL)
        check.add("project_environment", "PASS", "Loaded this project's .env; tracing disabled.")
        return True
    except Exception as exc:
        check.add("project_environment", "FAIL", f"Environment loading failed ({type(exc).__name__}).")
        return False


def verify_interpreter(check: Verification) -> None:
    correct = Path(sys.prefix).resolve() == (ROOT / ".venv").resolve()
    if correct:
        check.add("virtual_environment", "PASS", f"Project .venv; Python {sys.version.split()[0]}.")
    else:
        check.add("virtual_environment", "FAIL", "Run this script with the project's .venv/Scripts/python.exe.")


def verify_dependencies(check: Verification) -> None:
    dependencies = (
        "langchain", "langchain-core", "langgraph", "langchain-openai",
        "langchain-deepseek", "langchain-community", "langchain-mcp-adapters",
        "fastapi", "uvicorn", "httpx", "pydantic", "langchain-tavily",
    )
    versions = {}
    missing = []
    for package in dependencies:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            missing.append(package)
    check.report["versions"] = versions
    if missing:
        check.add("dependency_versions", "FAIL", "Missing packages: " + ", ".join(missing))
    else:
        check.add(
            "dependency_versions", "PASS",
            f"LangChain {versions['langchain']}; LangGraph {versions['langgraph']}; "
            f"FastAPI {versions['fastapi']}; remaining versions in report.",
        )
    if "langchain" in versions and versions["langchain"].split(".")[0] != "1":
        check.add("langchain_api", "FAIL", "This checkout requires the LangChain 1.x API.")
    try:
        # Includes compatibility-sensitive private imports and all server routes.
        for module in (
            "langchain.agents.middleware", "langgraph.runtime",
            "src.llms.providers.dashscope", "src.llms.llm", "src.agents.agents",
            "src.server.app",
        ):
            importlib.import_module(module)
        check.add("compatibility_imports", "PASS", "Original model adapters, agent middleware and FastAPI app import successfully.")
    except Exception as exc:
        # Never echo an exception message: providers may include credentials.
        check.add("compatibility_imports", "FAIL", f"Import failed ({type(exc).__name__}); no sensitive exception text saved.")


def verify_graph(check: Verification) -> None:
    try:
        from src.graph.builder import build_graph_with_memory

        graph = build_graph_with_memory()
        nodes = set(graph.get_graph().nodes)
        expected = {
            "coordinator", "planner", "human_feedback", "research_team",
            "researcher", "analyst", "coder", "reporter",
        }
        if not expected.issubset(nodes):
            check.add("original_state_graph", "FAIL", "The compiled graph is missing expected nodes.")
            return
        check.add("original_state_graph", "PASS", f"Original StateGraph compiled with an in-memory checkpointer ({len(nodes)} nodes); no model invoked.")
    except Exception as exc:
        check.add("original_state_graph", "FAIL", f"Graph compilation failed ({type(exc).__name__}).")


def verify_configuration(check: Verification) -> bool:
    try:
        from src.config.loader import load_yaml_config
        from src.llms.llm import _get_env_llm_conf

        config = load_yaml_config(str((ROOT / "conf.yaml").resolve()))
        basic = {**config.get("BASIC_MODEL", {}), **_get_env_llm_conf("basic")}
        parsed = urlsplit(str(basic.get("base_url", "")))
        if parsed.scheme != "https" or parsed.hostname != "api.deepseek.com":
            check.add("deepseek_configuration", "FAIL", "BASIC_MODEL must use the official HTTPS DeepSeek endpoint for this verification.")
            return False
        if not basic.get("model"):
            check.add("deepseek_configuration", "FAIL", "BASIC_MODEL.model is missing.")
            return False
        if basic.get("extra_body", {}).get("thinking", {}).get("type") != "disabled":
            check.add("deepseek_configuration", "FAIL", "Set BASIC_MODEL.extra_body.thinking.type to disabled before verifying the original tool loop.")
            return False
        check.add("deepseek_configuration", "PASS", "Official endpoint configured; thinking explicitly disabled.")
        key_present = has_deepseek_key()
        check.add(
            "deepseek_key", "PASS" if key_present else "WARN",
            "A key is present (not printed; validity untested)." if key_present
            else "DEEPSEEK_API_KEY is empty; services can start, live Agent execution is not verified.",
        )
        if key_present and str(basic.get("api_key", "")) != os.environ["DEEPSEEK_API_KEY"]:
            check.add("deepseek_key_binding", "FAIL", "BASIC_MODEL.api_key must reference this project's DEEPSEEK_API_KEY.")
            return False
        search = os.environ.get("SEARCH_API", "tavily").strip().lower()
        search_keys = {
            "tavily": "TAVILY_API_KEY", "infoquest": "INFOQUEST_API_KEY",
            "serper": "SERPER_API_KEY", "brave_search": "BRAVE_SEARCH_API_KEY",
        }
        required_key = search_keys.get(search)
        if required_key and not os.environ.get(required_key, "").strip():
            check.add("search_configuration", "WARN", "Configured search provider needs a separate key; online research is not ready.")
        elif search in {"duckduckgo", "arxiv", "wikipedia"}:
            check.add("search_configuration", "WARN", "Search needs no API key, but network reachability and real search results are untested.")
        else:
            check.add("search_configuration", "WARN", "Search is configured but not called; provider credentials and results are untested.")
        return True
    except Exception as exc:
        check.add("deepseek_configuration", "FAIL", f"Configuration check failed ({type(exc).__name__}).")
        return False


def verify_http(check: Verification, api_url: str, web_url: str) -> None:
    try:
        import httpx
    except ImportError:
        check.add("http_checks", "FAIL", "httpx is missing.")
        return
    targets = (
        ("backend_config", api_url.rstrip("/") + "/api/config", "config"),
        ("backend_rag_config", api_url.rstrip("/") + "/api/rag/config", "rag"),
        ("frontend_home", web_url.rstrip("/") + "/", "html"),
        ("frontend_chat", web_url.rstrip("/") + "/chat", "html"),
    )
    with httpx.Client(timeout=30, follow_redirects=True, trust_env=False) as client:
        for name, url, kind in targets:
            began = time.perf_counter()
            try:
                response = client.get(url)
                response.raise_for_status()
                if kind == "config":
                    body = response.json()
                    valid = isinstance(body.get("models"), dict) and isinstance(body.get("rag"), dict)
                elif kind == "rag":
                    valid = "provider" in response.json()
                else:
                    valid = "text/html" in response.headers.get("content-type", "") and "<html" in response.text.lower()
                if not valid:
                    check.add(name, "FAIL", "Unexpected response schema; response body not saved.")
                else:
                    check.add(name, "PASS", f"HTTP {response.status_code}; response format validated.", elapsed_seconds=round(time.perf_counter() - began, 3))
            except Exception as exc:
                check.add(name, "FAIL", f"HTTP check failed ({type(exc).__name__}); start the corresponding service and retry.", elapsed_seconds=round(time.perf_counter() - began, 3))


def text_content(message: Any) -> str:
    content = message.content
    if isinstance(content, str):
        return content.strip()
    return "".join(
        block.get("text", "") for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()


def token_counts(message: Any) -> dict[str, int]:
    usage = getattr(message, "usage_metadata", None) or {}
    return {
        key: int(usage[key]) for key in ("input_tokens", "output_tokens", "total_tokens")
        if isinstance(usage.get(key), int)
    }


def verify_live(check: Verification, config_valid: bool) -> None:
    if not config_valid or not has_deepseek_key():
        check.add("live_preflight", "FAIL", "Live verification requires valid configuration and a nonempty DEEPSEEK_API_KEY in this project's .env; no request sent.")
        return
    try:
        from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
        from langchain_core.tools import tool
        from src.llms.llm import get_llm_by_type

        model = get_llm_by_type("basic")
        # Keep paid verification bounded regardless of production retry settings.
        model.max_retries = 0
        model.request_timeout = 90
        model.max_tokens = 128

        def invoke(target: Any, messages: list[Any]) -> Any:
            check.report["remote_model_requests"] += 1
            began = time.perf_counter()
            result = target.invoke(messages)
            check.report.setdefault("model_calls", []).append({
                "elapsed_seconds": round(time.perf_counter() - began, 3),
                "tokens": token_counts(result),
            })
            return result

        plain = invoke(model, [HumanMessage(content="Reply with exactly READY and no other text.")])
        if text_content(plain) != "READY":
            check.add("live_text", "FAIL", "Short-text response did not match the expected result; output not saved.")
            return
        check.add("live_text", "PASS", "Original model adapter returned the expected short text.")

        @tool
        def verification_add(a: int, b: int) -> int:
            """Add two integers locally. This tool has no external side effects."""
            return a + b

        messages = [
            SystemMessage(content="Use verification_add to add the supplied integers. After the tool result, reply with only the resulting integer. Do not call any other tool."),
            HumanMessage(content="Add 17 and 25 using verification_add."),
        ]
        first = invoke(model.bind_tools([verification_add], tool_choice="verification_add"), messages)
        calls = getattr(first, "tool_calls", [])
        if len(calls) != 1 or calls[0].get("name") != "verification_add":
            check.add("live_tool_loop", "FAIL", "Expected exactly one addition tool call; model output not saved.")
            return
        call = calls[0]
        args = call.get("args", {})
        if args != {"a": 17, "b": 25} or not call.get("id"):
            check.add("live_tool_loop", "FAIL", "Tool arguments or identifier did not match the verification task.")
            return
        result = verification_add.invoke(args)
        if result != 42:
            check.add("live_tool_loop", "FAIL", "Local addition tool produced an unexpected result.")
            return
        final = invoke(model.bind_tools([verification_add]), [
            *messages, first,
            ToolMessage(content=str(result), tool_call_id=call["id"]),
        ])
        if text_content(final) != "42" or getattr(final, "tool_calls", []):
            check.add("live_tool_loop", "FAIL", "Final tool-loop reply did not match the expected result; output not saved.")
            return
        totals = {}
        for item in check.report.get("model_calls", []):
            for name, value in item["tokens"].items():
                totals[name] = totals.get(name, 0) + value
        check.report["total_tokens"] = totals
        check.add("live_tool_loop", "PASS", "Tool selection, local execution and second model reply verified; no external tool executed.")
    except Exception as exc:
        check.add("live_model", "FAIL", f"Model verification failed ({type(exc).__name__}); provider error text is intentionally omitted.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000", help="Backend origin without /api")
    parser.add_argument("--web-url", default="http://127.0.0.1:3000", help="Frontend origin")
    parser.add_argument("--offline", action="store_true", help="Skip service HTTP checks; verify local imports and configuration only")
    parser.add_argument("--live", action="store_true", help="Make up to three paid DeepSeek calls for text and a harmless local addition tool loop")
    args = parser.parse_args()
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    check = Verification("live" if args.live else "offline" if args.offline else "local_services")
    verify_interpreter(check)
    if not load_project_environment(check):
        return check.finish()
    verify_dependencies(check)
    verify_graph(check)
    config_valid = verify_configuration(check)
    if args.live and not has_deepseek_key():
        # Refuse before even HTTP checks, including user-supplied remote origins.
        check.add("live_preflight", "FAIL", "DEEPSEEK_API_KEY is empty or a placeholder; no HTTP or model request sent.")
        return check.finish()
    if args.offline:
        check.add("http_checks", "WARN", "Skipped by --offline; frontend and backend serving are unverified.")
    else:
        verify_http(check, args.api_url, args.web_url)
    if args.live:
        if any(item["status"] == "FAIL" for item in check.report["checks"]):
            check.add("live_preflight", "FAIL", "Resolve local verification failures before making model requests; no request sent.")
        else:
            verify_live(check, config_valid)
    else:
        check.add("live_model", "WARN", "Not requested; no remote LLM request sent. Use --live only after adding your key.")
    return check.finish()


if __name__ == "__main__":
    raise SystemExit(main())
