# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from functools import lru_cache

from src.config.tools import SELECTED_RAG_PROVIDER, RAGProvider
from src.rag.dify import DifyProvider
from src.rag.milvus import MilvusProvider
from src.rag.moi import MOIProvider
from src.rag.qdrant import QdrantProvider
from src.rag.ragflow import RAGFlowProvider
from src.rag.retriever import Retriever
from src.rag.vikingdb_knowledge_base import VikingDBKnowledgeBaseProvider


@lru_cache(maxsize=1)
def build_retriever() -> Retriever | None:
    # 本地 Qdrant 需要复用同一个客户端，避免重复打开磁盘目录并丢失会话内索引。
    if SELECTED_RAG_PROVIDER == RAGProvider.DIFY.value:
        return DifyProvider()
    if SELECTED_RAG_PROVIDER == RAGProvider.RAGFLOW.value:
        return RAGFlowProvider()
    elif SELECTED_RAG_PROVIDER == RAGProvider.MOI.value:
        return MOIProvider()
    elif SELECTED_RAG_PROVIDER == RAGProvider.VIKINGDB_KNOWLEDGE_BASE.value:
        return VikingDBKnowledgeBaseProvider()
    elif SELECTED_RAG_PROVIDER == RAGProvider.MILVUS.value:
        return MilvusProvider()
    elif SELECTED_RAG_PROVIDER == RAGProvider.QDRANT.value:
        return QdrantProvider()
    elif SELECTED_RAG_PROVIDER:
        raise ValueError(f"Unsupported RAG provider: {SELECTED_RAG_PROVIDER}")
    return None


def close_retriever() -> None:
    """Close a cached local vector database before the server exits."""
    if build_retriever.cache_info().currsize == 0:
        return

    retriever = build_retriever()
    try:
        if retriever is not None:
            close = getattr(retriever, "close", None)
            if callable(close):
                close()
    finally:
        # 清除缓存，保证下次启动或测试时不会复用已经关闭的客户端。
        build_retriever.cache_clear()
