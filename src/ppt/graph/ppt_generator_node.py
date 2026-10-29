# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import logging

from src.ppt.graph.state import PPTState
from src.ppt.service import render_marp_pptx

logger = logging.getLogger(__name__)


def ppt_generator_node(state: PPTState):
    logger.info("Generating ppt file...")
    ppt_bytes = render_marp_pptx(state["ppt_content"], state.get("theme", "default"))
    logger.info("Generated %d bytes of PPTX content", len(ppt_bytes))
    return {"ppt_bytes": ppt_bytes}
