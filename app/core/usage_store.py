"""按上游 Key 哈希的用量存储 (v2.1.0)。

SQLite 单表, 按 (key_hash, day) 聚合; 只存哈希与计数, 不存原文/明文 Key。
默认关闭 (USAGE_STORE_ENABLED=False); 开启后支持配额 (USAGE_DAY_QUOTA)。
"""

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


class UsageStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS usage (
                    key_hash TEXT NOT NULL,
                    day TEXT NOT NULL,
                    requests INTEGER NOT NULL DEFAULT 0,
                    errors INTEGER NOT NULL DEFAULT 0,
                    chars_in INTEGER NOT NULL DEFAULT 0,
                    chars_out INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (key_hash, day)
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    async def record(
        self,
        key_hash: str,
        requests: int = 1,
        errors: int = 0,
        chars_in: int = 0,
        chars_out: int = 0,
        day: str | None = None,
    ) -> None:
        day = day or _today()

        def _write() -> None:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO usage (key_hash, day, requests, errors, chars_in, chars_out)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(key_hash, day) DO UPDATE SET
                        requests = requests + excluded.requests,
                        errors = errors + excluded.errors,
                        chars_in = chars_in + excluded.chars_in,
                        chars_out = chars_out + excluded.chars_out
                    """,
                    (key_hash, day, requests, errors, chars_in, chars_out),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_write)

    async def today(self, key_hash: str, day: str | None = None) -> dict:
        day = day or _today()

        def _read() -> dict:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT requests, errors, chars_in, chars_out FROM usage WHERE key_hash=? AND day=?",
                    (key_hash, day),
                ).fetchone()
            finally:
                conn.close()
            if not row:
                return {"requests": 0, "errors": 0, "chars_in": 0, "chars_out": 0}
            return {
                "requests": row[0],
                "errors": row[1],
                "chars_in": row[2],
                "chars_out": row[3],
            }

        return await asyncio.to_thread(_read)

    async def totals(self, day: str | None = None) -> list[dict]:
        day = day or _today()

        def _read() -> list[dict]:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT key_hash, requests, errors, chars_in, chars_out FROM usage WHERE day=? ORDER BY requests DESC",
                    (day,),
                ).fetchall()
            finally:
                conn.close()
            return [
                {
                    "key_hash": r[0],
                    "requests": r[1],
                    "errors": r[2],
                    "chars_in": r[3],
                    "chars_out": r[4],
                }
                for r in rows
            ]

        return await asyncio.to_thread(_read)

    async def quota_exceeded(self, key_hash: str, quota: int, day: str | None = None) -> bool:
        if quota <= 0:
            return False
        today = await self.today(key_hash, day)
        return today["requests"] >= quota

    def close(self) -> None:
        return None  # 每调用独立连接, 无需常驻句柄
