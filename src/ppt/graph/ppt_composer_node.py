# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from src.config.agents import AGENT_LLM_MAP
from src.llms.llm import get_llm_by_type
from src.prompts.template import get_prompt_template

from .state import PPTState

logger = logging.getLogger(__name__)


def ppt_composer_node(state: PPTState):
    logger.info("Generating ppt content...")
    model = get_llm_by_type(AGENT_LLM_MAP["ppt_composer"])
    response = model.invoke(
        [
            SystemMessage(
                content=get_prompt_template(
                    "ppt/ppt_composer", locale=state.get("locale", "en-US")
                )
            ),
            HumanMessage(content=state["input"]),
        ],
    )
    ppt_content = response.content
    if not isinstance(ppt_content, str) or not ppt_content.strip():
        raise RuntimeError("The presentation model returned no slide content")
    # 中文注释：仅记录长度，不把可能包含用户资料的整份报告写入日志或项目目录。
    logger.info("Composed %d characters of presentation Markdown", len(ppt_content))
    return {"ppt_content": ppt_content}
