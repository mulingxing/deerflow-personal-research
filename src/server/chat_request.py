# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from typing import List, Literal, Optional, Union

from pydantic import BaseModel, Field

from src.config.report_style import ReportStyle
from src.rag.retriever import Resource


class ContentItem(BaseModel):
    type: str = Field(..., description="The type of content (text, image, etc.)")
    text: Optional[str] = Field(None, description="The text content if type is 'text'")
    image_url: Optional[str] = Field(
        None, description="The image URL if type is 'image'"
    )


class ChatMessage(BaseModel):
    role: str = Field(
        ..., description="The role of the message sender (user or assistant)"
    )
    content: Union[str, List[ContentItem]] = Field(
        ...,
        description="The message content as text or structured items",
    )


class ChatRequest(BaseModel):
    messages: Optional[List[ChatMessage]] = Field(
        [], description="History of messages between the user and the assistant"
    )
    conversation_history: List[ChatMessage] = Field(
        default_factory=list,
        max_length=12,
        description="Completed earlier turns, kept separate from the current question",
    )
    resources: Optional[List[Resource]] = Field(
        [], description="Resources to be used for the research"
    )
    debug: Optional[bool] = Field(False, description="Whether to enable debug logging")
    thread_id: Optional[str] = Field(
        "__default__", description="A specific conversation identifier"
    )
    locale: Optional[str] = Field(
        "en-US", description="Language locale for the conversation (e.g., en-US, zh-CN)"
    )
    max_plan_iterations: Optional[int] = Field(
        1, description="The maximum number of plan iterations"
    )
    max_step_num: Optional[int] = Field(
        3, description="The maximum number of steps in a plan"
    )
    max_search_results: Optional[int] = Field(
        3, description="The maximum number of search results"
    )
    auto_accepted_plan: Optional[bool] = Field(
        False, description="Whether to automatically accept the plan"
    )
    interrupt_feedback: Optional[str] = Field(
        None, description="Interrupt feedback from the user on the plan"
    )
    mcp_settings: Optional[dict] = Field(
        None, description="MCP settings for the chat request"
    )
    enable_background_investigation: Optional[bool] = Field(
        True, description="Whether to get background investigation before plan"
    )
    enable_web_search: Optional[bool] = Field(
        True,
        description="Whether to enable web search, set to False to use only local RAG",
    )
    report_style: Optional[ReportStyle] = Field(
        ReportStyle.ACADEMIC, description="The style of the report"
    )
    enable_deep_thinking: Optional[bool] = Field(
        False, description="Whether to enable deep thinking"
    )
    enable_clarification: Optional[bool] = Field(
        None,
        description="Whether to enable multi-turn clarification",
    )
    max_clarification_rounds: Optional[int] = Field(
        None,
        description="Maximum number of clarification rounds",
    )
    interrupt_before_tools: List[str] = Field(
        default_factory=list,
        description="Tool names to interrupt before execution",
    )


class TTSRequest(BaseModel):
    text: str = Field(..., description="The text to convert to speech")
    voice_type: Optional[str] = Field(
        "BV700_V2_streaming", description="The voice type to use"
    )
    encoding: Optional[str] = Field("mp3", description="The audio encoding format")
    speed_ratio: Optional[float] = Field(1.0, description="Speech speed ratio")
    volume_ratio: Optional[float] = Field(1.0, description="Speech volume ratio")
    pitch_ratio: Optional[float] = Field(1.0, description="Speech pitch ratio")
    text_type: Optional[str] = Field("plain", description="Text type (plain or ssml)")
    with_frontend: Optional[int] = Field(
        1, description="Whether to use frontend processing"
    )
    frontend_type: Optional[str] = Field("unitTson", description="Frontend type")


class GeneratePodcastRequest(BaseModel):
    content: str = Field(..., description="The content of the podcast")


class GeneratePPTRequest(BaseModel):
    content: str = Field(
        ...,
        min_length=1,
        max_length=200_000,
        description="Source text for the presentation",
    )
    locale: str = Field(
        "en-US", description="Language locale for the conversation (e.g., en-US, zh-CN)"
    )
    theme: Literal["default", "gaia", "uncover", "midnight", "paper"] = Field(
        "default", description="Visual theme of the generated presentation"
    )


class GenerateProseRequest(BaseModel):
    prompt: str = Field(..., description="The content of the prose")
    option: str = Field(..., description="The option of the prose writer")
    command: Optional[str] = Field(
        "", description="The user custom command of the prose writer"
    )


class EnhancePromptRequest(BaseModel):
    prompt: str = Field(..., description="The original prompt to enhance")
    context: Optional[str] = Field(
        "", description="Additional context about the intended use"
    )
    report_style: Optional[str] = Field(
        "academic", description="The style of the report"
    )
