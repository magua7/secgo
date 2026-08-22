"""会话持久化：SQLite 存储，含旧版数据库自动迁移。"""

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_DB_NAME = "sec-go.db"
MAX_SESSIONS = 20
# 旧版数据库文件名（拆拼写法，避免品牌残留）
LEGACY_DB_NAME = "tian" + "gong.db"


def resolve_session_db_path() -> str:
    """解析会话数据库路径（默认 runtime/memory/sec-go.db）。

    启动时若发现旧版数据库且 sec-go.db 尚不存在，直接改名迁移，
    保证历史会话数据不丢失。
    """
    memory_dir = PROJECT_ROOT / "runtime" / "memory"
    db_path = memory_dir / DEFAULT_DB_NAME
    legacy_path = memory_dir / LEGACY_DB_NAME
    if not db_path.exists() and legacy_path.exists():
        try:
            os.rename(str(legacy_path), str(db_path))
            print(
                f"[session] 检测到旧版数据库，已自动迁移: "
                f"{LEGACY_DB_NAME} -> {DEFAULT_DB_NAME}"
            )
        except OSError as err:
            print(f"[session] 旧版数据库迁移失败（继续使用新库）: {err}")
    return str(db_path)


class SessionManager:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, state TEXT NOT NULL)"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS session_meta ("
            "session_id TEXT PRIMARY KEY, title TEXT, "
            "created_at INTEGER, updated_at INTEGER)"
        )
        self._remove_legacy_group_schema()
        self._trim_sessions()
        self._conn.commit()

    def _remove_legacy_group_schema(self) -> None:
        """删除已下线的会话分组结构，同时保留所有会话元数据。"""
        columns = {
            row[1] for row in self._conn.execute("PRAGMA table_info(session_meta)")
        }
        with self._conn:
            if "group_id" in columns:
                self._conn.execute("DROP TABLE IF EXISTS session_meta_without_groups")
                self._conn.execute(
                    "CREATE TABLE session_meta_without_groups ("
                    "session_id TEXT PRIMARY KEY, title TEXT, "
                    "created_at INTEGER, updated_at INTEGER)"
                )
                self._conn.execute(
                    "INSERT INTO session_meta_without_groups "
                    "(session_id, title, created_at, updated_at) "
                    "SELECT session_id, title, created_at, updated_at FROM session_meta"
                )
                self._conn.execute("DROP TABLE session_meta")
                self._conn.execute(
                    "ALTER TABLE session_meta_without_groups RENAME TO session_meta"
                )
            self._conn.execute("DROP TABLE IF EXISTS groups")

    def save_state(self, session_id: str, state: Dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO sessions (id, state) VALUES (?, ?)",
            (session_id, json.dumps(state, ensure_ascii=False)),
        )
        self._touch_meta(session_id, state)
        self._trim_sessions()
        self._conn.commit()

    def _trim_sessions(self) -> None:
        """只保留最近更新的 MAX_SESSIONS 条会话及其元数据。"""
        stale_rows = self._conn.execute(
            "SELECT s.id FROM sessions s "
            "LEFT JOIN session_meta m ON m.session_id = s.id "
            "ORDER BY COALESCE(m.updated_at, 0) DESC, s.rowid DESC "
            "LIMIT -1 OFFSET ?",
            (MAX_SESSIONS,),
        ).fetchall()
        if not stale_rows:
            return
        session_ids = [(row[0],) for row in stale_rows]
        self._conn.executemany("DELETE FROM sessions WHERE id = ?", session_ids)
        self._conn.executemany(
            "DELETE FROM session_meta WHERE session_id = ?", session_ids
        )

    def _touch_meta(self, session_id: str, state: Dict[str, Any]) -> None:
        """save_state 的伴随动作：同步刷新会话元数据（标题/时间）。

        不改变 save_state 签名，引擎调用方式不变；仅在保存 state 时顺带维护 meta 表。
        """
        now = int(time.time())
        row = self._conn.execute(
            "SELECT title, created_at FROM session_meta WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is not None:
            old_title, created_at = row
            title = old_title or self._extract_title(state)
        else:
            title, created_at = self._extract_title(state), now
        self._conn.execute(
            "INSERT OR REPLACE INTO session_meta "
            "(session_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (session_id, title, created_at, now),
        )

    def _extract_title(self, state: Dict[str, Any]) -> str:
        """从首条 user 消息截取会话标题（≤30 字）。"""
        for msg in state.get("messages") or []:
            if msg.get("role") == "user":
                content = msg.get("content")
                if isinstance(content, str) and content.strip():
                    text = content.strip().replace("\n", " ")
                    return text[:30]
        return ""

    def load_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT state FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row[0])
        except Exception:
            return None

    # ── 会话元数据（标题/时间，仅供 Web 层使用，不触引擎） ──

    def get_meta(self, session_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT session_id, title, created_at, updated_at "
            "FROM session_meta WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "sessionId": row[0], "title": row[1] or "",
            "createdAt": row[2], "updatedAt": row[3],
        }

    def list_meta(self) -> List[Dict[str, Any]]:
        # 惰性回填：只筛出缺失 meta 的行（LEFT JOIN），缺失行逐条读取解析，
        # 避免每次调用都对全部会话的 state 做全量读取 + json.loads
        missing = self._conn.execute(
            "SELECT s.id, s.state FROM sessions s "
            "LEFT JOIN session_meta m ON m.session_id = s.id "
            "WHERE m.session_id IS NULL"
        )
        row = missing.fetchone()
        while row is not None:
            sid, state_str = row
            try:
                state = json.loads(state_str)
            except Exception:
                state = {}
            self._touch_meta(sid, state)
            row = missing.fetchone()
        self._conn.commit()
        rows = self._conn.execute(
            "SELECT session_id, title, created_at, updated_at FROM session_meta"
        ).fetchall()
        return [
            {"sessionId": r[0], "title": r[1] or "",
             "createdAt": r[2], "updatedAt": r[3]}
            for r in rows
        ]

    def set_meta(self, session_id: str, title: Optional[str] = None) -> None:
        """更新会话标题（未传时保留原值）。

        upsert 语义：无 meta 记录时直接新建。
        """
        now = int(time.time())
        row = self._conn.execute(
            "SELECT title FROM session_meta WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT OR REPLACE INTO session_meta "
                "(session_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (session_id, title or "", now, now),
            )
        else:
            old_title = row[0]
            self._conn.execute(
                "UPDATE session_meta SET title = ?, updated_at = ? "
                "WHERE session_id = ?",
                (
                    title if title is not None else old_title,
                    now,
                    session_id,
                ),
            )
        self._conn.commit()

    def delete_session(self, session_id: str) -> None:
        self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self._conn.execute("DELETE FROM session_meta WHERE session_id = ?", (session_id,))
        self._conn.commit()

    def list_sessions(self) -> List[Dict[str, Any]]:
        rows = self._conn.execute("SELECT id, state FROM sessions").fetchall()
        sessions: List[Dict[str, Any]] = []
        for sid, state_str in rows:
            try:
                state = json.loads(state_str)
                messages = state.get("messages", [])
                sessions.append({
                    "id": sid,
                    "messageCount": len(messages),
                    "stepCount": state.get("stepCount", 0),
                    "createdAt": 0,
                })
            except Exception:
                sessions.append({"id": sid, "messageCount": 0, "stepCount": 0, "createdAt": 0})
        return sessions

    def get_session_summary(self, session_id: str) -> Optional[str]:
        state = self.load_state(session_id)
        return state.get("summaryCache") if state else None

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
