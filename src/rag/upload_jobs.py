"""Small persistent status store for background RAG imports."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from threading import Lock
from typing import Any


class UploadJobStore:
    """Track imports across page refreshes and mark interrupted jobs on restart."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS rag_upload_jobs (
                    task_id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    resource_json TEXT,
                    error TEXT
                )
                """
            )
            self.interrupted_task_ids = [
                row[0]
                for row in connection.execute(
                    """
                    SELECT task_id FROM rag_upload_jobs
                    WHERE status IN ('queued', 'processing')
                    """
                ).fetchall()
            ]
            # 中文注释：服务重启会中断内存里的后台任务，不能继续显示“处理中”。
            connection.execute(
                """
                UPDATE rag_upload_jobs
                SET status = 'failed', error = 'Import interrupted by server restart'
                WHERE status IN ('queued', 'processing')
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path, timeout=10)

    def create(self, task_id: str, filename: str) -> dict[str, Any]:
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO rag_upload_jobs (task_id, filename, status, progress)
                VALUES (?, ?, 'queued', 0)
                """,
                (task_id, filename),
            )
        return self.get(task_id)

    def update(
        self,
        task_id: str,
        *,
        status: str,
        progress: int,
        resource: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE rag_upload_jobs
                SET status = ?, progress = ?, resource_json = ?, error = ?
                WHERE task_id = ?
                """,
                (
                    status,
                    progress,
                    json.dumps(resource, ensure_ascii=False) if resource else None,
                    error,
                    task_id,
                ),
            )

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._lock, closing(self._connect()) as connection, connection:
            row = connection.execute(
                """
                SELECT task_id, filename, status, progress, resource_json, error
                FROM rag_upload_jobs WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "task_id": row[0],
            "filename": row[1],
            "status": row[2],
            "progress": row[3],
            "resource": json.loads(row[4]) if row[4] else None,
            "error": row[5],
        }
