# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT


from langgraph.graph import MessagesState


class PPTState(MessagesState):
    """State for the ppt generation."""

    # Input
    input: str = ""
    locale: str = ""
    theme: str = "default"
    # Output
    ppt_bytes: bytes = b""

    # Assets
    ppt_content: str = ""
