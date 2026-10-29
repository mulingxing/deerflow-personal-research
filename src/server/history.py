"""本机聊天历史：用 SQLite 保存可恢复的前端会话快照。"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
CONVERSATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
ConversationStatus = Literal["idle", "running", "waiting_feedback", "needs_retry"]


class ConversationInput(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    status: ConversationStatus = "idle"
    snapshot: dict[str, Any] = Field(default_factory=dict)
    expected_updated_at: str | None = None

    @field_validator("title")
    @classmethod
    def non_blank_title(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("Conversation title cannot be empty")
        return title


class ConversationSummary(BaseModel):
    id: str
    title: str
    status: ConversationStatus
    created_at: str
    updated_at: str


class ConversationDetail(ConversationSummary):
    snapshot: dict[str, Any]


class ConversationList(BaseModel):
    conversations: list[ConversationSummary]


class ConversationHistoryStore:
    """每次请求使用短连接，避免长时间持有数据库文件锁。"""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def recover_interrupted(self) -> None:
        """仅在真实服务启动时调用；单纯导入模块不能修改正在运行的会话。"""
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                UPDATE conversations SET status = 'needs_retry', updated_at = ?
                WHERE status IN ('running', 'waiting_feedback')
                """,
                (datetime.now(UTC).isoformat(),),
            )

    @contextmanager
    def _connection(self):
        with closing(sqlite3.connect(self.database_path, timeout=10)) as connection:
            connection.row_factory = sqlite3.Row
            with connection:
                yield connection

    def save(self, conversation_id: str, data: ConversationInput) -> ConversationDetail:
        snapshot_json = json.dumps(
            data.snapshot, ensure_ascii=False, separators=(",", ":")
        )
        if len(snapshot_json.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
            raise ValueError("Conversation snapshot is too large")

        with self._lock, self._connection() as connection:
            current = connection.execute(
                "SELECT updated_at FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if current is None and data.expected_updated_at is not None:
                raise ConversationConflictError()
            if (
                current is not None
                and data.expected_updated_at != current["updated_at"]
            ):
                raise ConversationConflictError()
            now_time = datetime.now(UTC)
            if current is not None:
                previous = datetime.fromisoformat(current["updated_at"])
                if now_time <= previous:
                    now_time = previous + timedelta(microseconds=1)
            now = now_time.isoformat()
            connection.execute(
                """
                INSERT INTO conversations
                    (id, title, status, snapshot_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    status = excluded.status,
                    snapshot_json = excluded.snapshot_json,
                    updated_at = excluded.updated_at
                """,
                (conversation_id, data.title, data.status, snapshot_json, now, now),
            )
        detail = self.get(conversation_id)
        assert detail is not None
        return detail

    def get(self, conversation_id: str) -> ConversationDetail | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """
                SELECT id, title, status, snapshot_json, created_at, updated_at
                FROM conversations WHERE id = ?
                """,
                (conversation_id,),
            ).fetchone()
        if row is None:
            return None
        return ConversationDetail(
            id=row["id"],
            title=row["title"],
            status=row["status"],
            snapshot=json.loads(row["snapshot_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list(self, limit: int = 50, offset: int = 0) -> list[ConversationSummary]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, title, status, created_at, updated_at
                FROM conversations
                ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [ConversationSummary(**dict(row)) for row in rows]

    def delete(
        self, conversation_id: str, expected_updated_at: str | None = None
    ) -> bool:
        with self._lock, self._connection() as connection:
            current = connection.execute(
                "SELECT updated_at FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if current is None:
                return False
            if (
                expected_updated_at is not None
                and expected_updated_at != current["updated_at"]
            ):
                raise ConversationConflictError()
            cursor = connection.execute(
                "DELETE FROM conversations WHERE id = ?", (conversation_id,)
            )
            return cursor.rowcount > 0


class ConversationConflictError(Exception):
    """Another browser tab saved a newer copy of this conversation."""


router = APIRouter(prefix="/api/conversations", tags=["conversations"])
history_store = ConversationHistoryStore(
    Path(__file__).resolve().parents[2] / ".runtime" / "conversations.sqlite3"
)


def _validate_id(conversation_id: str) -> None:
    if not CONVERSATION_ID_PATTERN.fullmatch(conversation_id):
        raise HTTPException(status_code=400, detail="Invalid conversation ID")


@router.get("", response_model=ConversationList)
def list_conversations(
    limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)
):
    return ConversationList(conversations=history_store.list(limit, offset))


@router.put("/{conversation_id}", response_model=ConversationDetail)
def save_conversation(conversation_id: str, data: ConversationInput):
    _validate_id(conversation_id)
    try:
        return history_store.save(conversation_id, data)
    except ConversationConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail="Conversation changed in another tab. Refresh before saving.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: str):
    _validate_id(conversation_id)
    detail = history_store.get(conversation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return detail


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: str, expected_updated_at: str | None = Query(None)
):
    _validate_id(conversation_id)
    try:
        if not history_store.delete(conversation_id, expected_updated_at):
            raise HTTPException(status_code=404, detail="Conversation not found")
    except ConversationConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail="Conversation changed in another tab. Refresh before deleting.",
        ) from exc
