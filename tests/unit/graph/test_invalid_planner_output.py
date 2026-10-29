"""回归测试：非计划文本不能进入研究计划确认流程。"""

import json
from unittest.mock import MagicMock, patch

from langchain_core.messages import HumanMessage

from src.graph.nodes import human_feedback_node, planner_node


def _configurable(max_plan_iterations: int = 1) -> MagicMock:
    config = MagicMock()
    config.enable_deep_thinking = False
    config.enable_web_search = False
    config.enforce_web_search = False
    config.max_plan_iterations = max_plan_iterations
    config.resources = []
    return config


def test_markdown_report_cannot_be_confirmed_as_plan() -> None:
    # 真实故障中的 [[1]] 引用会被 json_repair 误识别为数组。
    report = "# 核查报告\n\n资料中没有三步复习法 [[1]](#ref-1)。"
    response = MagicMock()
    response.model_dump_json.return_value = json.dumps({"content": report})
    llm = MagicMock()
    llm.invoke.return_value = response
    state = {
        "messages": [HumanMessage(content="资料里的三步复习法是什么？")],
        "plan_iterations": 0,
        "locale": "zh-CN",
    }

    with (
        patch("src.graph.nodes.Configuration.from_runnable_config", return_value=_configurable()),
        patch("src.graph.nodes.apply_prompt_template", return_value=[]),
        patch("src.graph.nodes.get_llm_by_type", return_value=llm),
    ):
        result = planner_node(state, {})

    assert result.goto == "__end__"
    assert "current_plan" not in result.update
    assert "研究计划生成失败" in result.update["messages"][0].content


def test_valid_json_plan_still_reaches_feedback() -> None:
    plan = {
        "locale": "zh-CN",
        "has_enough_context": False,
        "thought": "先在所选资料中定位原文。",
        "title": "三步复习法核查计划",
        "steps": [
            {
                "need_search": True,
                "title": "检索资料",
                "description": "查找三步复习法的原文并记录来源。",
                "step_type": "research",
            }
        ],
    }
    response = MagicMock()
    response.model_dump_json.return_value = json.dumps({"content": json.dumps(plan)})
    llm = MagicMock()
    llm.invoke.return_value = response
    state = {
        "messages": [HumanMessage(content="资料里的三步复习法是什么？")],
        "plan_iterations": 0,
        "locale": "zh-CN",
    }

    with (
        patch("src.graph.nodes.Configuration.from_runnable_config", return_value=_configurable()),
        patch("src.graph.nodes.apply_prompt_template", return_value=[]),
        patch("src.graph.nodes.get_llm_by_type", return_value=llm),
    ):
        result = planner_node(state, {})

    assert result.goto == "human_feedback"
    assert isinstance(result.update["current_plan"], str)


def test_selected_source_requires_retrieval_even_if_model_claims_enough_context() -> None:
    plan = {
        "locale": "zh-CN",
        "has_enough_context": True,
        "thought": "需要在所选资料中核对。",
        "title": "所选资料核查计划",
        "steps": [
            {
                "need_search": True,
                "title": "检索所选资料",
                "description": "定位原文并记录出处。",
                "step_type": "research",
            }
        ],
    }
    response = MagicMock()
    response.model_dump_json.return_value = json.dumps({"content": json.dumps(plan)})
    llm = MagicMock()
    llm.invoke.return_value = response
    config = _configurable()
    config.resources = [object()]
    state = {"messages": [HumanMessage(content="只依据所选资料回答")], "locale": "zh-CN"}

    with (
        patch("src.graph.nodes.Configuration.from_runnable_config", return_value=config),
        patch("src.graph.nodes.apply_prompt_template", return_value=[]),
        patch("src.graph.nodes.get_llm_by_type", return_value=llm),
    ):
        result = planner_node(state, {})

    assert result.goto == "human_feedback"


def test_selected_source_without_retrieval_step_is_rejected() -> None:
    plan = {
        "locale": "zh-CN",
        "has_enough_context": True,
        "thought": "历史回答已经足够。",
        "title": "直接回答",
        "steps": [],
    }
    response = MagicMock()
    response.model_dump_json.return_value = json.dumps({"content": json.dumps(plan)})
    llm = MagicMock()
    llm.invoke.return_value = response
    config = _configurable()
    config.resources = [object()]
    state = {"messages": [HumanMessage(content="只依据所选资料回答")], "locale": "zh-CN"}

    with (
        patch("src.graph.nodes.Configuration.from_runnable_config", return_value=config),
        patch("src.graph.nodes.apply_prompt_template", return_value=[]),
        patch("src.graph.nodes.get_llm_by_type", return_value=llm),
    ):
        result = planner_node(state, {})

    assert result.goto == "__end__"
    assert "研究计划生成失败" in result.update["messages"][0].content


def test_accepting_saved_invalid_plan_returns_clear_error() -> None:
    state = {
        "current_plan": "# 核查报告\n\n资料中没有相关内容 [[1]](#ref-1)。",
        "plan_iterations": 0,
        "locale": "zh-CN",
        "auto_accepted_plan": False,
    }

    with (
        patch("src.graph.nodes.interrupt", return_value="[ACCEPTED] 开始研究"),
        patch("src.graph.nodes.Configuration.from_runnable_config", return_value=_configurable()),
    ):
        result = human_feedback_node(state, {})

    assert result.goto == "__end__"
    assert "无法继续研究" in result.update["messages"][0].content
