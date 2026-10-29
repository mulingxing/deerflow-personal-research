# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import asyncio
import hashlib
import itertools
import logging
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set

from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from openai import OpenAI
from qdrant_client import QdrantClient, grpc
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSelectorInclude,
    PointStruct,
    VectorParams,
)

from src.config.loader import get_bool_env, get_int_env, get_str_env
from src.rag.retriever import Chunk, Document, Resource, Retriever

logger = logging.getLogger(__name__)

SCROLL_SIZE = 64
UPSERT_BATCH_SIZE = 32


class DashscopeEmbeddings:
    def __init__(self, **kwargs: Any) -> None:
        self._client: OpenAI = OpenAI(
            api_key=kwargs.get("api_key", ""), base_url=kwargs.get("base_url", "")
        )
        self._model: str = kwargs.get("model", "")
        self._encoding_format: str = kwargs.get("encoding_format", "float")

    def _embed(self, texts: Sequence[str]) -> List[List[float]]:
        clean_texts = [t if isinstance(t, str) else str(t) for t in texts]
        if not clean_texts:
            return []
        resp = self._client.embeddings.create(
            model=self._model,
            input=clean_texts,
            encoding_format=self._encoding_format,
        )
        return [d.embedding for d in resp.data]

    def embed_query(self, text: str) -> List[float]:
        embeddings = self._embed([text])
        return embeddings[0] if embeddings else []

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._embed(texts)


class FastEmbedEmbeddings:
    """按需加载本地中文向量模型，避免浏览资料列表时触发下载。"""

    def __init__(self, model_name: str, cache_dir: Path) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir
        self._model: Any = None
        self._lock = threading.Lock()

    def _load_model(self) -> Any:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    try:
                        from fastembed import TextEmbedding
                    except ImportError as exc:
                        raise RuntimeError(
                            "FastEmbed is missing. Install project dependencies first."
                        ) from exc
                    self.cache_dir.mkdir(parents=True, exist_ok=True)
                    try:
                        self._model = TextEmbedding(
                            model_name=self.model_name,
                            cache_dir=str(self.cache_dir),
                        )
                    except Exception as exc:
                        raise RuntimeError(
                            f"Could not load FastEmbed model {self.model_name}. "
                            "Check network and cache; first use downloads the model."
                        ) from exc
        return self._model

    def embed_query(self, text: str) -> List[float]:
        vector = next(iter(self._load_model().query_embed(text)))
        return [float(value) for value in vector]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        vectors = self._load_model().passage_embed(texts)
        return [[float(value) for value in vector] for vector in vectors]


class QdrantProvider(Retriever):
    def __init__(self) -> None:
        self.location: str = get_str_env("QDRANT_LOCATION", ":memory:")
        self.api_key: str = get_str_env("QDRANT_API_KEY", "")
        self.collection_name: str = get_str_env("QDRANT_COLLECTION", "documents")

        top_k_raw = get_str_env("QDRANT_TOP_K", "10")
        self.top_k: int = int(top_k_raw) if top_k_raw.isdigit() else 10

        self.embedding_provider = get_str_env("QDRANT_EMBEDDING_PROVIDER", "openai")
        default_model = (
            "BAAI/bge-small-zh-v1.5"
            if self.embedding_provider.lower() == "fastembed"
            else ""
        )
        self.embedding_model_name = get_str_env("QDRANT_EMBEDDING_MODEL", default_model)
        self.embedding_api_key = get_str_env("QDRANT_EMBEDDING_API_KEY")
        self.embedding_base_url = get_str_env("QDRANT_EMBEDDING_BASE_URL")
        self.embedding_dim: int = self._get_embedding_dimension(
            self.embedding_model_name
        )

        self.auto_load_examples: bool = get_bool_env("QDRANT_AUTO_LOAD_EXAMPLES", True)
        self.examples_dir: str = get_str_env("QDRANT_EXAMPLES_DIR", "examples")
        self.chunk_size: int = get_int_env("QDRANT_CHUNK_SIZE", 4000)

        self._init_embedding_model()

        self.client: Any = None
        self.vector_store: Any = None
        self._connection_lock = threading.Lock()

    def _init_embedding_model(self) -> None:
        kwargs = {
            "api_key": self.embedding_api_key,
            "model": self.embedding_model_name,
            "base_url": self.embedding_base_url,
            "encoding_format": "float",
            "dimensions": self.embedding_dim,
        }
        if self.embedding_provider.lower() == "openai":
            self.embedding_model = OpenAIEmbeddings(**kwargs)
        elif self.embedding_provider.lower() == "dashscope":
            self.embedding_model = DashscopeEmbeddings(**kwargs)
        elif self.embedding_provider.lower() == "fastembed":
            project_root = Path(__file__).resolve().parents[2]
            self.embedding_model = FastEmbedEmbeddings(
                model_name=self.embedding_model_name,
                cache_dir=project_root / ".cache" / "fastembed",
            )
        else:
            raise ValueError(
                f"Unsupported embedding provider: {self.embedding_provider}. "
                "Supported providers: openai, dashscope, fastembed"
            )

    def _get_embedding_dimension(self, model_name: str) -> int:
        embedding_dims = {
            "text-embedding-ada-002": 1536,
            "text-embedding-v4": 2048,
            "BAAI/bge-small-zh-v1.5": 512,
        }

        explicit_dim = get_int_env("QDRANT_EMBEDDING_DIM", 0)
        if explicit_dim > 0:
            return explicit_dim
        return embedding_dims.get(model_name, 1536)

    def _ensure_collection_exists(self) -> None:
        if not self.client.collection_exists(self.collection_name):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=self.embedding_dim, distance=Distance.COSINE
                ),
            )
            logger.info("Created Qdrant collection: %s", self.collection_name)

    def _load_example_files(self) -> None:
        current_file = Path(__file__)
        project_root = current_file.parent.parent.parent
        examples_path = project_root / self.examples_dir

        if not examples_path.exists():
            logger.info("Examples directory not found: %s", examples_path)
            return

        logger.info("Loading example files from: %s", examples_path)

        md_files = list(examples_path.glob("*.md"))
        if not md_files:
            logger.info("No markdown files found in examples directory")
            return

        existing_docs = self._get_existing_document_ids()
        loaded_count = 0
        for md_file in md_files:
            doc_id = self._generate_doc_id(md_file)

            if doc_id in existing_docs:
                continue

            try:
                content = md_file.read_text(encoding="utf-8")
                title = self._extract_title_from_markdown(content, md_file.name)

                chunks = self._split_content(content)

                for i, chunk in enumerate(chunks):
                    chunk_id = f"{doc_id}_chunk_{i}" if len(chunks) > 1 else doc_id
                    self._insert_document_chunk(
                        doc_id=chunk_id,
                        content=chunk,
                        title=title,
                        url=f"qdrant://{self.collection_name}/{md_file.name}",
                        metadata={"source": "examples", "file": md_file.name},
                    )

                loaded_count += 1
                logger.debug("Loaded example markdown: %s", md_file.name)

            except Exception as e:
                logger.warning("Error loading %s: %s", md_file.name, e)

        logger.info("Successfully loaded %d example files into Qdrant", loaded_count)

    def _generate_doc_id(self, file_path: Path) -> str:
        file_stat = file_path.stat()
        content_hash = hashlib.md5(
            f"{file_path.name}_{file_stat.st_size}_{file_stat.st_mtime}".encode()
        ).hexdigest()[:8]
        return f"example_{file_path.stem}_{content_hash}"

    def _extract_title_from_markdown(self, content: str, filename: str) -> str:
        lines = content.split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith("# "):
                return line[2:].strip()

        return Path(filename).stem.replace("_", " ").title()

    def _split_content(self, content: str) -> List[str]:
        """按段落切块，并继续拆分超长段落。"""
        limit = max(1, self.chunk_size)
        chunks: List[str] = []
        current = ""

        for raw_paragraph in content.split("\n\n"):
            paragraph = raw_paragraph.strip()
            if not paragraph:
                continue

            if current and len(current) + 2 + len(paragraph) > limit:
                chunks.append(current)
                current = ""

            while len(paragraph) > limit:
                chunks.append(paragraph[:limit])
                paragraph = paragraph[limit:]

            if paragraph:
                current = f"{current}\n\n{paragraph}" if current else paragraph

        if current:
            chunks.append(current)
        return chunks

    def _string_to_uuid(self, text: str) -> str:
        namespace = uuid.NAMESPACE_DNS
        return str(uuid.uuid5(namespace, text))

    def _scroll_all_points(
        self,
        scroll_filter: Optional[Filter] = None,
        with_payload: Any = True,
        with_vectors: bool = False,
    ) -> List[Any]:
        return list(self._iter_points(scroll_filter, with_payload, with_vectors))

    def _iter_points(
        self,
        scroll_filter: Optional[Filter] = None,
        with_payload: Any = True,
        with_vectors: bool = False,
    ):
        """逐页读取点，资料列表无需一次保存全部文本。"""
        next_offset = None
        stop_scrolling = False

        while not stop_scrolling:
            points, next_offset = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=scroll_filter,
                limit=SCROLL_SIZE,
                offset=next_offset,
                with_payload=with_payload,
                with_vectors=with_vectors,
            )
            stop_scrolling = next_offset is None or (
                isinstance(next_offset, grpc.PointId)
                and getattr(next_offset, "num", 0) == 0
                and getattr(next_offset, "uuid", "") == ""
            )
            yield from points

    def _get_existing_document_ids(self) -> Set[str]:
        try:
            points = self._scroll_all_points(with_payload=True, with_vectors=False)
            return {
                point.payload.get("doc_id", str(point.id))
                for point in points
                if point.payload
            }
        except Exception:
            return set()

    def _insert_document_chunk(
        self, doc_id: str, content: str, title: str, url: str, metadata: Dict[str, Any]
    ) -> None:
        embedding = self._get_embedding(content)

        payload = {
            "doc_id": doc_id,
            "content": content,
            "title": title,
            "url": url,
            **metadata,
        }

        point_id = self._string_to_uuid(doc_id)
        point = PointStruct(id=point_id, vector=embedding, payload=payload)

        self.client.upsert(
            collection_name=self.collection_name, points=[point], wait=True
        )

    def _connect(self) -> None:
        with self._connection_lock:
            if self.client is not None:
                return
            # 相对路径按项目根目录定位，避免不同启动目录生成不同知识库。
            if self.location != ":memory:" and "://" not in self.location:
                local_path = Path(self.location).expanduser()
                if not local_path.is_absolute():
                    local_path = Path(__file__).resolve().parents[2] / local_path
                local_path = local_path.resolve()
                local_path.mkdir(parents=True, exist_ok=True)
                client_kwargs = {"path": str(local_path)}
            else:
                client_kwargs = {"location": self.location}
                if self.api_key:
                    client_kwargs["api_key"] = self.api_key
            self.client = QdrantClient(**client_kwargs)
            try:
                self._ensure_collection_exists()
            except Exception:
                self.close()
                raise

            try:
                self.vector_store = QdrantVectorStore(
                    client=self.client,
                    collection_name=self.collection_name,
                    embedding=self.embedding_model,
                    validate_collection_config=False,
                )
            except Exception:
                self.vector_store = None

    def _get_embedding(self, text: str) -> List[float]:
        return self.embedding_model.embed_query(text=text.strip())

    def ingest_file(
        self, file_content: bytes, filename: str, **kwargs: Any
    ) -> Resource:
        """保存上传文件的文本片段及其来源位置。"""
        safe_filename = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
        if not safe_filename or safe_filename in {".", ".."}:
            raise ValueError("A valid filename is required")

        supplied_chunks = kwargs.get("chunks")
        if supplied_chunks is None:
            try:
                content = file_content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("Only UTF-8 text files are supported") from exc
            supplied_chunks = [{"content": content}]

        if not isinstance(supplied_chunks, list):
            raise ValueError("chunks must be a list")

        total_chunks = 0
        for item in supplied_chunks:
            if not isinstance(item, dict) or not isinstance(item.get("content"), str):
                raise ValueError("Each chunk must contain text content")
            total_chunks += len(self._split_content(item["content"]))

        if not total_chunks:
            raise ValueError("The file contains no readable text")

        def iter_chunks():
            for item in supplied_chunks:
                for piece in self._split_content(item["content"]):
                    yield {
                        "content": piece,
                        "page_number": item.get("page_number"),
                        "section": item.get("section"),
                    }

        prepared_chunks = iter_chunks()
        first_chunk = next(prepared_chunks)

        if not self.client:
            self._connect()

        first_text = first_chunk["content"]
        title = (
            self._extract_title_from_markdown(first_text, safe_filename)
            if safe_filename.lower().endswith(".md")
            else Path(safe_filename).stem.replace("_", " ")
        )
        resource_id = f"uploaded_{uuid.uuid4().hex}"
        uri = f"qdrant://{self.collection_name}/{resource_id}"
        inserted_ids: List[str] = []
        progress_callback = kwargs.get("progress_callback")
        try:
            numbered_chunks = enumerate(itertools.chain([first_chunk], prepared_chunks))
            while batch := list(itertools.islice(numbered_chunks, UPSERT_BATCH_SIZE)):
                vectors = self.embedding_model.embed_documents(
                    [item["content"] for _, item in batch]
                )
                if len(vectors) != len(batch):
                    raise ValueError("Embedding model returned an incomplete batch")

                points = []
                for (index, item), vector in zip(batch, vectors):
                    if len(vector) != self.embedding_dim:
                        raise ValueError(
                            "Embedding dimension does not match collection"
                        )
                    point_id = self._string_to_uuid(f"{resource_id}_chunk_{index}")
                    payload = {
                        "doc_id": f"{resource_id}_chunk_{index}",
                        "resource_id": resource_id,
                        "content": item["content"],
                        "title": title,
                        "url": uri,
                        "source": "uploaded",
                        "file": safe_filename,
                    }
                    if item["page_number"] is not None:
                        payload["page_number"] = item["page_number"]
                    if item["section"]:
                        payload["section"] = item["section"]
                    points.append(
                        PointStruct(id=point_id, vector=vector, payload=payload)
                    )
                    inserted_ids.append(point_id)

                self.client.upsert(
                    collection_name=self.collection_name, points=points, wait=True
                )
                if progress_callback:
                    done = batch[-1][0] + 1
                    progress_callback(done, total_chunks)
        except Exception as exc:
            # 分块写入失败时清理已插入的点，避免展示不完整资料。
            if inserted_ids:
                try:
                    self.client.delete(
                        collection_name=self.collection_name,
                        points_selector=inserted_ids,
                    )
                except Exception:
                    logger.exception("Could not roll back incomplete Qdrant upload")
            raise RuntimeError("Failed to ingest the uploaded file") from exc

        return Resource(
            uri=uri,
            title=title,
            description="Uploaded file",
            filename=safe_filename,
        )

    def list_resources(self, query: Optional[str] = None) -> List[Resource]:
        if self.client is None:
            self._connect()

        try:
            # 资源选择面板必须同时看到示例和用户上传的文件。
            all_points = self._iter_points(
                scroll_filter=Filter(
                    should=[
                        FieldCondition(
                            key="source", match=MatchValue(value="examples")
                        ),
                        FieldCondition(
                            key="source", match=MatchValue(value="uploaded")
                        ),
                    ]
                ),
                with_payload=PayloadSelectorInclude(
                    include=["resource_id", "doc_id", "url", "title", "file", "source"]
                ),
                with_vectors=False,
            )
            resources: List[Resource] = []
            seen_uris: Set[str] = set()
            name_query = (query or "").strip().casefold()
            for point in all_points:
                payload = point.payload or {}
                doc_id = payload.get("resource_id") or payload.get(
                    "doc_id", str(point.id)
                )
                uri = payload.get("url", "") or f"qdrant://{doc_id}"
                title = payload.get("title", "") or payload.get("file", "") or doc_id
                if uri in seen_uris:
                    continue
                if name_query and not any(
                    name_query in str(value).casefold()
                    for value in (title, payload.get("file", ""))
                ):
                    continue
                seen_uris.add(uri)
                resources.append(
                    Resource(
                        uri=uri,
                        title=title,
                        description=(
                            "Uploaded file"
                            if payload.get("source") == "uploaded"
                            else "Stored Qdrant document"
                        ),
                        # 已有索引保留原文件名，同名 PDF 和 Word 也能区分。
                        filename=(
                            payload.get("file") or None
                            if payload.get("source") == "uploaded"
                            else None
                        ),
                    )
                )

            logger.info(
                "Successfully listed %d resources from Qdrant collection: %s",
                len(resources),
                self.collection_name,
            )
        except Exception:
            # 查询失败时明确报错，避免把尚未入库的示例文件显示成可检索资料。
            logger.exception("Failed to list Qdrant resources")
            raise
        return resources

    async def list_resources_async(self, query: Optional[str] = None) -> List[Resource]:
        """
        Asynchronous version of list_resources.
        Run the synchronous implementation in a worker thread.
        """
        return await asyncio.to_thread(self.list_resources, query)

    def _list_local_markdown_resources(self) -> List[Resource]:
        current_file = Path(__file__)
        project_root = current_file.parent.parent.parent
        examples_path = project_root / self.examples_dir
        if not examples_path.exists():
            return []

        md_files = list(examples_path.glob("*.md"))
        resources: list[Resource] = []
        for md_file in md_files:
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
                title = self._extract_title_from_markdown(content, md_file.name)
                uri = f"qdrant://{self.collection_name}/{md_file.name}"
                resources.append(
                    Resource(
                        uri=uri,
                        title=title,
                        description="Local markdown example (not yet ingested)",
                    )
                )
            except Exception:
                continue
        return resources

    def query_relevant_documents(
        self, query: str, resources: Optional[List[Resource]] = None
    ) -> List[Document]:
        resources = resources or []
        if not self.client:
            self._connect()

        query_embedding = self._get_embedding(query)

        search_kwargs: Dict[str, Any] = {
            "collection_name": self.collection_name,
            "query": query_embedding,
            "limit": self.top_k,
            "with_payload": True,
        }
        if resources:
            # 先限定所选资料再做向量排序，避免其他文件占满 top_k。
            source_conditions = []
            for resource in resources:
                if not resource.uri:
                    continue
                source_conditions.append(
                    FieldCondition(key="url", match=MatchValue(value=resource.uri))
                )
                source_conditions.append(
                    FieldCondition(
                        key="resource_id",
                        match=MatchValue(value=resource.uri.rsplit("/", 1)[-1]),
                    )
                )
            if not source_conditions:
                return []
            search_kwargs["query_filter"] = Filter(should=source_conditions)

        search_results = self.client.query_points(**search_kwargs).points

        documents = {}

        for result in search_results:
            payload = result.payload or {}
            doc_id = payload.get("resource_id") or payload.get("doc_id", str(result.id))
            content = payload.get("content", "")
            title = payload.get("title", "")
            url = payload.get("url", "")
            score = result.score

            if doc_id not in documents:
                documents[doc_id] = Document(id=doc_id, url=url, title=title, chunks=[])

            chunk = Chunk(
                content=content,
                similarity=score,
                page_number=payload.get("page_number"),
                section=payload.get("section"),
            )
            documents[doc_id].chunks.append(chunk)

        return list(documents.values())

    async def query_relevant_documents_async(
        self, query: str, resources: Optional[List[Resource]] = None
    ) -> List[Document]:
        """
        Asynchronous version of query_relevant_documents.
        Run the synchronous implementation in a worker thread.
        """
        return await asyncio.to_thread(self.query_relevant_documents, query, resources)

    def create_collection(self) -> None:
        if not self.client:
            self._connect()
        else:
            self._ensure_collection_exists()

    def load_examples(self, force_reload: bool = False) -> None:
        if not self.client:
            self._connect()

        if force_reload:
            self._clear_example_documents()

        self._load_example_files()

    def _clear_example_documents(self) -> None:
        try:
            all_points = self._scroll_all_points(
                scroll_filter=Filter(
                    must=[
                        FieldCondition(key="source", match=MatchValue(value="examples"))
                    ]
                ),
                with_payload=False,
                with_vectors=False,
            )

            if all_points:
                point_ids = [str(point.id) for point in all_points]
                self.client.delete(
                    collection_name=self.collection_name, points_selector=point_ids
                )
                logger.info("Cleared %d existing example documents", len(point_ids))

        except Exception as e:
            logger.warning("Could not clear existing examples: %s", e)

    def get_loaded_examples(self) -> List[Dict[str, str]]:
        if not self.client:
            self._connect()

        all_points = self._scroll_all_points(
            scroll_filter=Filter(
                must=[FieldCondition(key="source", match=MatchValue(value="examples"))]
            ),
            with_payload=True,
            with_vectors=False,
        )

        examples = []
        for point in all_points:
            payload = point.payload or {}
            examples.append(
                {
                    "id": payload.get("doc_id", str(point.id)),
                    "title": payload.get("title", ""),
                    "file": payload.get("file", ""),
                    "url": payload.get("url", ""),
                }
            )

        return examples

    def close(self) -> None:
        if hasattr(self, "client") and self.client:
            try:
                if hasattr(self.client, "close"):
                    self.client.close()
                self.client = None
                self.vector_store = None
            except Exception as e:
                logger.warning("Exception occurred while closing QdrantProvider: %s", e)

    def __del__(self) -> None:
        self.close()


def load_examples() -> None:
    auto_load_examples = get_bool_env("QDRANT_AUTO_LOAD_EXAMPLES", False)
    rag_provider = get_str_env("RAG_PROVIDER", "")
    if rag_provider == "qdrant" and auto_load_examples:
        provider = QdrantProvider()
        provider.load_examples()
