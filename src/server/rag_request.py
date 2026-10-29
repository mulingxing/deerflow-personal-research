# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from typing import Literal

from pydantic import BaseModel, Field

from src.rag.retriever import Resource


class RAGConfigResponse(BaseModel):
    """Response model for RAG config."""

    provider: str | None = Field(
        None, description="The provider of the RAG, default is ragflow"
    )


class RAGResourceRequest(BaseModel):
    """Request model for RAG resource."""

    query: str | None = Field(
        None, description="The query of the resource need to be searched"
    )


class RAGResourcesResponse(BaseModel):
    """Response model for RAG resources."""

    resources: list[Resource] = Field(..., description="The resources of the RAG")


class RAGUploadJobResponse(BaseModel):
    """Progress of a document being parsed and added to the knowledge base."""

    task_id: str
    filename: str
    status: Literal["queued", "processing", "completed", "failed"]
    progress: int = Field(ge=0, le=100)
    resource: Resource | None = None
    error: str | None = None
