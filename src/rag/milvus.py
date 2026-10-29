# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import asyncio
import hashlib
import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from langchain_milvus.vectorstores import Milvus as LangchainMilvus
from langchain_openai import OpenAIEmbeddings
from openai import OpenAI
from pymilvus import CollectionSchema, DataType, FieldSchema, MilvusClient

from src.config.loader import get_bool_env, get_int_env, get_str_env
from src.rag.retriever import Chunk, Document, Resource, Retriever

logger = logging.getLogger(__name__)


class DashscopeEmbeddings:
    """OpenAI-compatible embeddings wrapper."""

    def __init__(self, **kwargs: Any) -> None:
        self._client: OpenAI = OpenAI(
            api_key=kwargs.get("api_key", ""), base_url=kwargs.get("base_url", "")
        )
        self._model: str = kwargs.get("model", "")
        self._encoding_format: str = kwargs.get("encoding_format", "float")

    def _embed(self, texts: Sequence[str]) -> List[List[float]]:
        """Internal helper performing the embedding API call."""
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
        """Return embedding for a given text."""
        embeddings = self._embed([text])
        return embeddings[0] if embeddings else []

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Return embeddings for multiple documents (LangChain interface)."""
        return self._embed(texts)


class MilvusRetriever(Retriever):
    """Retriever implementation backed by a Milvus vector store.
    Responsibilities:
        * Initialize / lazily connect to Milvus (local Lite or remote server).
        * Provide methods for inserting content chunks & querying similarity.
        * Optionally surface example markdown resources found in the project.
    Environment variables (selected):
        MILVUS_URI: Connection URI or local *.db path for Milvus Lite.
        MILVUS_COLLECTION: Target collection name (default: documents).
        MILVUS_TOP_K: Result set size (default: 10).
        MILVUS_EMBEDDING_PROVIDER: openai | dashscope (default: openai).
        MILVUS_EMBEDDING_MODEL: Embedding model name.
        MILVUS_EMBEDDING_DIM: Override embedding dimensionality.
        MILVUS_AUTO_LOAD_EXAMPLES: Load example *.md files if true.
        MILVUS_EXAMPLES_DIR: Folder containing example markdown files.
    """

    def __init__(self) -> None:
        # --- Connection / collection configuration ---
        self.uri: str = get_str_env("MILVUS_URI", "http://localhost:19530")
        self.user: str = get_str_env("MILVUS_USER")
        self.password: str = get_str_env("MILVUS_PASSWORD")
        self.collection_name: str = get_str_env("MILVUS_COLLECTION", "documents")

        # --- Search configuration ---
        top_k_raw = get_str_env("MILVUS_TOP_K", "10")
        self.top_k: int = int(top_k_raw) if top_k_raw.isdigit() else 10

        # --- Vector field names ---
        self.vector_field: str = get_str_env("MILVUS_VECTOR_FIELD", "embedding")
        self.id_field: str = get_str_env("MILVUS_ID_FIELD", "id")
        self.content_field: str = get_str_env("MILVUS_CONTENT_FIELD", "content")
        self.title_field: str = get_str_env("MILVUS_TITLE_FIELD", "title")
        self.url_field: str = get_str_env("MILVUS_URL_FIELD", "url")
        self.metadata_field: str = get_str_env("MILVUS_METADATA_FIELD", "metadata")

        # --- Embedding configuration ---
        self.embedding_model = get_str_env("MILVUS_EMBEDDING_MODEL")
        self.embedding_api_key = get_str_env("MILVUS_EMBEDDING_API_KEY")
        self.embedding_base_url = get_str_env("MILVUS_EMBEDDING_BASE_URL")
        self.embedding_dim: int = self._get_embedding_dimension(self.embedding_model)
        self.embedding_provider = get_str_env("MILVUS_EMBEDDING_PROVIDER", "openai")

        # --- Examples / auto-load configuration ---
        self.auto_load_examples: bool = get_bool_env("MILVUS_AUTO_LOAD_EXAMPLES", True)
        self.examples_dir: str = get_str_env("MILVUS_EXAMPLES_DIR", "examples")
        # chunk size
        self.chunk_size: int = get_int_env("MILVUS_CHUNK_SIZE", 4000)

        # --- Embedding model initialization ---
        self._init_embedding_model()

        # Client (MilvusClient or LangchainMilvus) created lazily
        self.client: Any = None

    def _init_embedding_model(self) -> None:
        """Initialize the embedding model based on configuration."""
        kwargs = {
            "api_key": self.embedding_api_key,
            "model": self.embedding_model,
            "base_url": self.embedding_base_url,
            "encoding_format": "float",
            "dimensions": self.embedding_dim,
        }
        if self.embedding_provider.lower() == "openai":
            self.embedding_model = OpenAIEmbeddings(**kwargs)
        elif self.embedding_provider.lower() == "dashscope":
            self.embedding_model = DashscopeEmbeddings(**kwargs)
        else:
            raise ValueError(
                f"Unsupported embedding provider: {self.embedding_provider}. "
                "Supported providers: openai, dashscope"
            )

    def _get_embedding_dimension(self, model_name: str) -> int:
        """Return embedding dimension for the supplied model name."""
        # Common OpenAI embedding model dimensions
        embedding_dims = {
            "text-embedding-ada-002": 1536,
            "text-embedding-v4": 2048,
        }

        # Check if user has explicitly set the dimension
        explicit_dim = get_int_env("MILVUS_EMBEDDING_DIM", 0)
        if explicit_dim > 0:
            return explicit_dim
        # Return the dimension for the specified model
        return embedding_dims.get(model_name, 1536)  # Default to 1536

    def _create_collection_schema(self) -> CollectionSchema:
        """Build and return a Milvus ``CollectionSchema`` object with metadata field.
        Attempts to use a JSON field for metadata; falls back to VARCHAR if JSON
        type isn't supported in the deployment.
        """
        fields = [
            FieldSchema(
                name=self.id_field,
                dtype=DataType.VARCHAR,
                max_length=512,
                is_primary=True,
                auto_id=False,
            ),
            FieldSchema(
                name=self.vector_field,
                dtype=DataType.FLOAT_VECTOR,
                dim=self.embedding_dim,
            ),
            FieldSchema(
                name=self.content_field, dtype=DataType.VARCHAR, max_length=65535
            ),
            FieldSchema(name=self.title_field, dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name=self.url_field, dtype=DataType.VARCHAR, max_length=1024),
        ]

        schema = CollectionSchema(
            fields=fields,
            description=f"DeerFlow RAG documents: {self.collection_name}",
            enable_dynamic_field=True,  # Allow additional dynamic metadata fields
        )
        return schema

    def _ensure_collection_exists(self) -> None:
        """Ensure the configured collection exists (create if missing).
        For Milvus Lite we create the collection manually; for the remote
        (LangChain) client we rely on LangChain's internal logic.
        """
        if self._is_milvus_lite():
            # For Milvus Lite, use MilvusClient
            try:
                # Check if collection exists
                collections = self.client.list_collections()
                if self.collection_name not in collections:
                    # Create collection
                    schema = self._create_collection_schema()
                    self.client.create_collection(
                        collection_name=self.collection_name,
                        schema=schema,
                        index_params={
                            "field_name": self.vector_field,
                            "index_type": "IVF_FLAT",
                            "metric_type": "IP",
                            "params": {"nlist": 1024},
                        },
                    )
                    logger.info("Created Milvus collection: %s", self.collection_name)

            except Exception as e:
                logger.warning("Could not ensure collection exists: %s", e)
        else:
            # For LangChain Milvus, collection creation is handled automatically
            logger.warning(
                "Could not ensure collection exists: %s", self.collection_name
            )

    def _load_example_files(self) -> None:
        """Load example markdown files into the collection (idempotent).
        Each markdown file is split into chunks and inserted only if a chunk
        with the derived document id hasn't been previously stored.
        """
        try:
            # Get the project root directory
            current_file = Path(__file__)
            project_root = current_file.parent.parent.parent  # Go up to project root
            examples_path = project_root / self.examples_dir

            if not examples_path.exists():
                logger.info("Examples directory not found: %s", examples_path)
                return

            logger.info("Loading example files from: %s", examples_path)

            # Find all markdown files
            md_files = list(examples_path.glob("*.md"))
            if not md_files:
                logger.info("No markdown files found in examples directory")
                return
            # Check if files are already loaded
            existing_docs = self._get_existing_document_ids()
            loaded_count = 0
            for md_file in md_files:
                doc_id = self._generate_doc_id(md_file)

                # Skip if already loaded
                if doc_id in existing_docs:
                    continue
                try:
                    # Read and process the file
                    content = md_file.read_text(encoding="utf-8")
                    title = self._extract_title_from_markdown(content, md_file.name)

                    # Split content into chunks if it's too long
                    chunks = self._split_content(content)

                    # Insert each chunk
                    for i, chunk in enumerate(chunks):
                        chunk_id = f"{doc_id}_chunk_{i}" if len(chunks) > 1 else doc_id
                        self._insert_document_chunk(
                            doc_id=chunk_id,
                            content=chunk,
                            title=title,
                            url=f"milvus://{self.collection_name}/{md_file.name}",
                            metadata={"source": "examples", "file": md_file.name},
                        )

                    loaded_count += 1
                    logger.debug("Loaded example markdown: %s", md_file.name)

                except Exception as e:
                    logger.warning("Error loading %s: %s", md_file.name, e)

            logger.info(
                "Successfully loaded %d example files into Milvus", loaded_count
            )

        except Exception as e:
            logger.error("Error loading example files: %s", e)

    def _generate_doc_id(self, file_path: Path) -> str:
        """Return a stable identifier derived from name, size & mtime hash."""
        # Use file name and size for a simple but effective ID
        file_stat = file_path.stat()
        content_hash = hashlib.md5(
            f"{file_path.name}_{file_stat.st_size}_{file_stat.st_mtime}".encode()
        ).hexdigest()[:8]
        return f"example_{file_path.stem}_{content_hash}"

    def _extract_title_from_markdown(self, content: str, filename: str) -> str:
        """Extract the first level-1 heading; else derive from file name."""
        lines = content.split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith("# "):
                return line[2:].strip()

        # Fallback to filename without extension
        return Path(filename).stem.replace("_", " ").title()

    def _split_content(self, content: str) -> List[str]:
        """按段落切块，并保证超长段落也不会超过目标长度。"""
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

    def _get_existing_document_ids(self) -> Set[str]:
        """Return set of existing document identifiers in the collection."""
        try:
            if self._is_milvus_lite():
                results = self.client.query(
                    collection_name=self.collection_name,
                    filter="",
                    output_fields=[self.id_field],
                    limit=10000,
                )
                return {
                    result.get(self.id_field, "")
                    for result in results
                    if result.get(self.id_field)
                }
            else:
                # For LangChain Milvus, we can't easily query all IDs
                # Return no IDs so LangChain can handle duplicate inserts.
                return set()
        except Exception:
            return set()

    def _insert_document_chunk(
        self, doc_id: str, content: str, title: str, url: str, metadata: Dict[str, Any]
    ) -> None:
        """Insert a single content chunk into Milvus."""
        try:
            # Generate embedding
            embedding = self._get_embedding(content)

            if self._is_milvus_lite():
                # For Milvus Lite, use MilvusClient
                data = [
                    {
                        self.id_field: doc_id,
                        self.vector_field: embedding,
                        self.content_field: content,
                        self.title_field: title,
                        self.url_field: url,
                        **metadata,  # Add metadata fields
                    }
                ]
                self.client.insert(collection_name=self.collection_name, data=data)
            else:
                # For LangChain Milvus, use add_texts
                self.client.add_texts(
                    texts=[content],
                    metadatas=[
                        {
                            self.id_field: doc_id,
                            self.title_field: title,
                            self.url_field: url,
                            **metadata,
                        }
                    ],
                )
        except Exception as e:
            raise RuntimeError(f"Failed to insert document chunk: {str(e)}")

    def _connect(self) -> None:
        """Create the underlying Milvus client (idempotent)."""
        try:
            # Check if using Milvus Lite (file-based) vs server-based Milvus
            if self._is_milvus_lite():
                # Use MilvusClient for Milvus Lite (local file database)
                self.client = MilvusClient(self.uri)
                # Ensure collection exists
                self._ensure_collection_exists()
            else:
                connection_args = {
                    "uri": self.uri,
                }
                # Add user/password only if provided
                if self.user:
                    connection_args["user"] = self.user
                if self.password:
                    connection_args["password"] = self.password

                # LangChain creates the collection when needed.
                self.client = LangchainMilvus(
                    embedding_function=self.embedding_model,
                    collection_name=self.collection_name,
                    connection_args=connection_args,
                    # Existing collections may use a different schema.
                    drop_old=False,
                    enable_dynamic_field=True,
                )
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Milvus: {str(e)}")

    def _is_milvus_lite(self) -> bool:
        """Return True if the URI points to a local Milvus Lite file.
        Milvus Lite uses local file paths (often ``*.db``) without an HTTP/HTTPS
        scheme. We treat any path not containing a protocol and not starting
        with an HTTP(S) prefix as a Lite instance.
        """
        return self.uri.endswith(".db") or (
            not self.uri.startswith(("http://", "https://")) and "://" not in self.uri
        )

    def _get_embedding(self, text: str) -> List[float]:
        """Return embedding for a given text."""
        try:
            # Validate input
            if not isinstance(text, str):
                raise ValueError(f"Text must be a string, got {type(text)}")

            if not text.strip():
                raise ValueError("Text cannot be empty or only whitespace")
            # Both supported embedding providers expose the same interface.
            embeddings = self.embedding_model.embed_query(text=text.strip())

            # Validate output
            if not isinstance(embeddings, list) or not embeddings:
                raise ValueError(f"Invalid embedding format: {type(embeddings)}")

            return embeddings
        except Exception as e:
            raise RuntimeError(f"Failed to generate embedding: {str(e)}")

    def list_resources(self, query: Optional[str] = None) -> List[Resource]:
        """根据向量库中的元数据列出示例和上传文件。"""
        resources: List[Resource] = []
        seen_uris: Set[str] = set()
        name_query = (query or "").strip().casefold()

        # Ensure connection established
        if not self.client:
            try:
                self._connect()
            except Exception:
                # Fall back to only local examples if connection fails
                return self._list_local_markdown_resources()

        try:
            for meta in self._iter_stored_resource_rows(query):
                uri = (
                    meta.get(self.url_field, "")
                    or f"milvus://{meta.get(self.id_field, '')}"
                )
                title = meta.get(self.title_field, "") or meta.get(
                    self.id_field, "Unnamed"
                )
                if uri in seen_uris:
                    continue
                if name_query and not any(
                    name_query in str(value).casefold()
                    for value in (title, meta.get("file", ""))
                ):
                    continue
                seen_uris.add(uri)
                resources.append(
                    Resource(
                        uri=uri,
                        title=title,
                        description=(
                            "Uploaded file"
                            if meta.get("source") == "uploaded"
                            else "Stored Milvus document"
                        ),
                        filename=(
                            meta.get("file") or None
                            if meta.get("source") == "uploaded"
                            else None
                        ),
                    )
                )
        except Exception:
            logger.warning(
                "Failed to query Milvus for resources, falling back to local examples."
            )
            # Fall back to only local examples if connection fails
            return self._list_local_markdown_resources()
        return resources

    def _iter_stored_resource_rows(self, query: Optional[str]):
        """Milvus 迭代读取元数据，避免大文件的分块占满列表上限。"""
        source_filter = 'source in ["examples", "uploaded"]'
        fields = [self.id_field, self.title_field, self.url_field, "source", "file"]
        if self._is_milvus_lite():
            target = self.client
            params = {"collection_name": self.collection_name, "filter": source_filter}
        elif getattr(self.client, "col", None) is not None:
            target = self.client.col
            params = {"expr": source_filter}
        else:
            # 旧版客户端没有元数据查询入口时保留兼容路径。
            docs: Iterable[Any] = self.client.similarity_search(
                query or " ", k=100, expr=source_filter
            )
            for doc in docs:
                yield getattr(doc, "metadata", {}) or {}
            return

        if hasattr(target, "query_iterator"):
            iterator = target.query_iterator(
                **params, output_fields=fields, batch_size=1000
            )
            try:
                while rows := iterator.next():
                    yield from rows
            finally:
                iterator.close()
        else:
            yield from target.query(**params, output_fields=fields, limit=1000)

    async def list_resources_async(self, query: Optional[str] = None) -> List[Resource]:
        """
        Asynchronous version of list_resources.
        Run the synchronous implementation in a worker thread.
        """
        return await asyncio.to_thread(self.list_resources, query)

    def _list_local_markdown_resources(self) -> List[Resource]:
        """Return local example markdown files as ``Resource`` objects.

        These are surfaced even when not ingested so users can choose to load
        them. Controlled by directory presence only (lightweight)."""
        current_file = Path(__file__)
        project_root = current_file.parent.parent.parent  # up to project root
        examples_path = project_root / self.examples_dir
        if not examples_path.exists():
            return []

        md_files = list(examples_path.glob("*.md"))
        resources: list[Resource] = []
        for md_file in md_files:
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
                title = self._extract_title_from_markdown(content, md_file.name)
                uri = f"milvus://{self.collection_name}/{md_file.name}"
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
        """Perform vector similarity search returning rich ``Document`` objects.

        Args:
            query: Natural language query string.
            resources: Optional subset filter of ``Resource`` objects; if
                provided, only documents whose id/url appear in the list will
                be included.

        Returns:
            List of aggregated ``Document`` objects; each contains one or more
            ``Chunk`` instances (one per matched piece of content).

        Raises:
            RuntimeError: On underlying search errors.
        """
        resources = resources or []
        try:
            if not self.client:
                self._connect()

            # Get embeddings for the query
            query_embedding = self._get_embedding(query)
            resource_filter = self._build_resource_filter(resources)
            if resources and not resource_filter:
                return []

            # For Milvus Lite, use MilvusClient directly
            if self._is_milvus_lite():
                # Perform vector search
                search_kwargs: Dict[str, Any] = {
                    "collection_name": self.collection_name,
                    "data": [query_embedding],
                    "anns_field": self.vector_field,
                    "param": {"metric_type": "IP", "params": {"nprobe": 10}},
                    "limit": self.top_k,
                    "output_fields": [
                        self.id_field,
                        self.content_field,
                        self.title_field,
                        self.url_field,
                        "resource_id",
                        "page_number",
                        "section",
                    ],
                }
                if resource_filter:
                    # 必须在 top_k 排序前过滤资料。
                    search_kwargs["filter"] = resource_filter
                search_results = self.client.search(**search_kwargs)

                documents = {}

                for result_list in search_results:
                    for result in result_list:
                        entity = result.get("entity", {})
                        doc_id = entity.get("resource_id") or entity.get(
                            self.id_field, ""
                        )
                        content = entity.get(self.content_field, "")
                        title = entity.get(self.title_field, "")
                        url = entity.get(self.url_field, "")
                        score = result.get("distance", 0.0)

                        # Keep results from selected resources only.
                        if resources:
                            doc_in_resources = False
                            for resource in resources:
                                if (
                                    url and url in resource.uri
                                ) or doc_id in resource.uri:
                                    doc_in_resources = True
                                    break
                            if not doc_in_resources:
                                continue

                        # Create or update document
                        if doc_id not in documents:
                            documents[doc_id] = Document(
                                id=doc_id, url=url, title=title, chunks=[]
                            )

                        # Add chunk to document
                        chunk = Chunk(
                            content=content,
                            similarity=score,
                            page_number=entity.get("page_number"),
                            section=entity.get("section"),
                        )
                        documents[doc_id].chunks.append(chunk)

                return list(documents.values())

            else:
                # For LangChain Milvus, use similarity search
                search_kwargs = {"query": query, "k": self.top_k}
                if resource_filter:
                    search_kwargs["expr"] = resource_filter
                search_results = self.client.similarity_search_with_score(
                    **search_kwargs
                )

                documents = {}

                for doc, score in search_results:
                    metadata = doc.metadata or {}
                    doc_id = metadata.get("resource_id") or metadata.get(
                        self.id_field, ""
                    )
                    title = metadata.get(self.title_field, "")
                    url = metadata.get(self.url_field, "")
                    content = doc.page_content

                    # Keep results from selected resources only.
                    if resources:
                        doc_in_resources = False
                        for resource in resources:
                            if (url and url in resource.uri) or doc_id in resource.uri:
                                doc_in_resources = True
                                break
                        if not doc_in_resources:
                            continue

                    # Create or update document
                    if doc_id not in documents:
                        documents[doc_id] = Document(
                            id=doc_id, url=url, title=title, chunks=[]
                        )

                    # Add chunk to document
                    chunk = Chunk(
                        content=content,
                        similarity=score,
                        page_number=metadata.get("page_number"),
                        section=metadata.get("section"),
                    )
                    documents[doc_id].chunks.append(chunk)

                return list(documents.values())

        except Exception as e:
            raise RuntimeError(f"Failed to query documents from Milvus: {str(e)}")

    def _build_resource_filter(self, resources: List[Resource]) -> str:
        """用所选资料的 URI 构造服务端过滤表达式。"""
        uris = sorted({resource.uri for resource in resources if resource.uri})
        if not uris:
            return ""
        ids = sorted({uri.rsplit("/", 1)[-1] for uri in uris})
        url_values = ", ".join(json.dumps(uri, ensure_ascii=False) for uri in uris)
        id_values = ", ".join(json.dumps(doc_id, ensure_ascii=False) for doc_id in ids)
        return f"{self.url_field} in [{url_values}] or {self.id_field} in [{id_values}]"

    async def query_relevant_documents_async(
        self, query: str, resources: Optional[List[Resource]] = None
    ) -> List[Document]:
        """
        Asynchronous version of query_relevant_documents.
        Run the synchronous implementation in a worker thread.
        """
        return await asyncio.to_thread(self.query_relevant_documents, query, resources)

    def create_collection(self) -> None:
        """Public hook ensuring collection exists (explicit initialization)."""
        if not self.client:
            self._connect()
        else:
            # If we're using Milvus Lite, ensure collection exists
            if self._is_milvus_lite():
                self._ensure_collection_exists()

    def load_examples(self, force_reload: bool = False) -> None:
        """Load example markdown files, optionally clearing existing ones.

        Args:
            force_reload: If True existing example documents are deleted first.
        """
        if not self.client:
            self._connect()

        if force_reload:
            # Clear existing examples
            self._clear_example_documents()

        self._load_example_files()

    def _clear_example_documents(self) -> None:
        """Delete previously ingested example documents (Milvus Lite only)."""
        try:
            if self._is_milvus_lite():
                # For Milvus Lite, delete documents with source='examples'
                # Note: Milvus doesn't support direct delete by filter in all versions
                # So we'll query and delete by IDs
                results = self.client.query(
                    collection_name=self.collection_name,
                    filter="source == 'examples'",
                    output_fields=[self.id_field],
                    limit=10000,
                )

                if results:
                    doc_ids = [result[self.id_field] for result in results]
                    self.client.delete(
                        collection_name=self.collection_name, ids=doc_ids
                    )
                    logger.info("Cleared %d existing example documents", len(doc_ids))
            else:
                # For LangChain Milvus, we can't easily delete by metadata
                logger.info("Clearing examples is not supported by this Milvus client")

        except Exception as e:
            logger.warning("Could not clear existing examples: %s", e)

    def get_loaded_examples(self) -> List[Dict[str, str]]:
        """Return metadata for previously ingested example documents."""
        try:
            if not self.client:
                self._connect()

            if self._is_milvus_lite():
                results = self.client.query(
                    collection_name=self.collection_name,
                    filter="source == 'examples'",
                    output_fields=[
                        self.id_field,
                        self.title_field,
                        self.url_field,
                        "source",
                        "file",
                    ],
                    limit=1000,
                )

                examples = []
                for result in results:
                    examples.append(
                        {
                            "id": result.get(self.id_field, ""),
                            "title": result.get(self.title_field, ""),
                            "file": result.get("file", ""),
                            "url": result.get(self.url_field, ""),
                        }
                    )

                return examples
            else:
                # For LangChain Milvus, we can't easily filter by metadata
                logger.info(
                    "Getting loaded examples not supported for LangChain Milvus client"
                )
                return []

        except Exception as e:
            logger.error("Error getting loaded examples: %s", e)
            return []

    def close(self) -> None:
        """Release underlying client resources (idempotent)."""
        if hasattr(self, "client") and self.client:
            try:
                # For Milvus Lite (MilvusClient), close the connection
                if self._is_milvus_lite() and hasattr(self.client, "close"):
                    self.client.close()
                # For LangChain Milvus, no explicit close method needed
                self.client = None
            except Exception:
                # Ignore errors during cleanup
                pass

    def _sanitize_filename(self, filename: str, max_length: int = 200) -> str:
        """Sanitize filename for safe use in doc_id and URI construction.

        Args:
            filename: Original filename to sanitize.
            max_length: Maximum allowed length for the filename (default: 200).

        Returns:
            Sanitized filename safe for storage and URI construction.
        """
        # Extract basename to remove any path components
        sanitized = Path(filename).name

        # Remove or replace problematic characters
        # Keep alphanumeric, dots, hyphens, underscores; replace others with underscore
        sanitized = re.sub(r"[^\w.\-]", "_", sanitized)

        # Collapse multiple underscores
        sanitized = re.sub(r"_+", "_", sanitized)

        # Remove leading/trailing underscores and dots
        sanitized = sanitized.strip("_.")

        # Ensure we have a valid filename
        if not sanitized:
            sanitized = "unnamed_file"

        # Truncate if too long, preserving extension
        if len(sanitized) > max_length:
            # Try to preserve extension
            parts = sanitized.rsplit(".", 1)
            if len(parts) == 2 and len(parts[1]) <= 10:
                ext = "." + parts[1]
                base = parts[0][: max_length - len(ext)]
                sanitized = base + ext
            else:
                sanitized = sanitized[:max_length]

        return sanitized

    def _check_duplicate_file(self, filename: str) -> bool:
        """Check if a file with the same name has been uploaded before."""
        file_filter = (
            f"file == {json.dumps(filename, ensure_ascii=False)} "
            'and source == "uploaded"'
        )
        try:
            if self._is_milvus_lite():
                results = self.client.query(
                    collection_name=self.collection_name,
                    filter=file_filter,
                    output_fields=[self.id_field],
                    limit=1,
                )
                return len(results) > 0
            else:
                # For LangChain Milvus, perform a search with metadata filter
                docs = self.client.similarity_search(
                    "",
                    k=1,
                    expr=file_filter,
                )
                return len(docs) > 0
        except Exception:
            # If check fails, allow upload to proceed
            return False

    def ingest_file(self, file_content: bytes, filename: str, **kwargs) -> Resource:
        """将 UTF-8 文本或已解析的分页文本片段写入 Milvus。"""
        # Check connection
        if not self.client:
            self._connect()

        # Sanitize filename to prevent issues with special characters and path traversal
        safe_filename = self._sanitize_filename(filename)
        if safe_filename != filename:
            logger.debug("Filename sanitized: '%s' -> '%s'", filename, safe_filename)

        supplied_chunks = kwargs.get("chunks")
        if supplied_chunks is None:
            try:
                content = file_content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("Only UTF-8 text files are supported") from exc
            supplied_chunks = [{"content": content}]

        if not isinstance(supplied_chunks, list):
            raise ValueError("chunks must be a list")

        prepared_chunks: List[Dict[str, Any]] = []
        for item in supplied_chunks:
            if not isinstance(item, dict) or not isinstance(item.get("content"), str):
                raise ValueError("Each chunk must contain text content")
            for piece in self._split_content(item["content"]):
                prepared_chunks.append(
                    {
                        "content": piece,
                        "page_number": item.get("page_number"),
                        "section": item.get("section"),
                    }
                )

        if not prepared_chunks:
            raise ValueError("The file contains no readable text")

        # Check for existing file with same name
        is_duplicate = self._check_duplicate_file(safe_filename)
        if is_duplicate:
            logger.info(
                "File '%s' was previously uploaded. Creating new version.",
                safe_filename,
            )

        # 每次上传拥有独立 URI，重名文件的不同版本仍可分别检索。
        timestamp = int(time.time() * 1000)
        doc_id = f"uploaded_{uuid.uuid4().hex}"
        uri = f"milvus://{self.collection_name}/{doc_id}"
        title = (
            self._extract_title_from_markdown(
                prepared_chunks[0]["content"], safe_filename
            )
            if safe_filename.lower().endswith(".md")
            else Path(safe_filename).stem.replace("_", " ")
        )

        progress_callback = kwargs.get("progress_callback")
        for i, item in enumerate(prepared_chunks):
            chunk_id = f"{doc_id}_chunk_{i}"
            metadata = {
                "source": "uploaded",
                "file": safe_filename,
                "resource_id": doc_id,
                "timestamp": timestamp,
            }
            if item["page_number"] is not None:
                metadata["page_number"] = item["page_number"]
            if item["section"]:
                metadata["section"] = item["section"]
            self._insert_document_chunk(
                doc_id=chunk_id,
                content=item["content"],
                title=title,
                url=uri,
                metadata=metadata,
            )
            if progress_callback and (
                (i + 1) % 8 == 0 or i + 1 == len(prepared_chunks)
            ):
                progress_callback(i + 1, len(prepared_chunks))

        description = "Uploaded file (new version)" if is_duplicate else "Uploaded file"
        return Resource(
            uri=uri,
            title=title,
            description=description,
            filename=safe_filename,
        )

    def __del__(self) -> None:  # pragma: no cover - best-effort cleanup
        """Best-effort cleanup when instance is garbage collected."""
        self.close()


# Backwards compatibility export (original class name kept for external imports)
class MilvusProvider(MilvusRetriever):
    """Backward compatible alias for ``MilvusRetriever`` (original name)."""

    pass


def load_examples() -> None:
    auto_load_examples = get_bool_env("MILVUS_AUTO_LOAD_EXAMPLES", False)
    rag_provider = get_str_env("RAG_PROVIDER", "")
    if rag_provider == "milvus" and auto_load_examples:
        provider = MilvusProvider()
        provider.load_examples()
