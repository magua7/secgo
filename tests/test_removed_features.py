from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from secgo.runtime.session import SessionManager
from secgo.web import server


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RemovedFeaturesTests(unittest.TestCase):
    def test_legacy_frontend_archive_is_absent(self) -> None:
        legacy_dir = PROJECT_ROOT / "secgo" / "web" / "static" / "legacy"

        self.assertFalse(legacy_dir.exists(), f"旧前端仍存在：{legacy_dir}")

    def test_group_routes_are_not_registered(self) -> None:
        routes = {route.path for route in server.app.routes}
        removed_routes = {
            "/api/groups",
            "/api/groups/{group_id}",
            "/api/sessions/{session_id}/group",
        }

        self.assertTrue(
            removed_routes.isdisjoint(routes),
            f"分组接口仍存在：{sorted(removed_routes & routes)}",
        )

    def test_legacy_group_schema_is_removed_without_losing_session_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "sessions.db"
            connection = sqlite3.connect(db_path)
            connection.execute(
                "CREATE TABLE sessions (id TEXT PRIMARY KEY, state TEXT NOT NULL, updated_at REAL NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE session_meta ("
                "session_id TEXT PRIMARY KEY, group_id TEXT NOT NULL DEFAULT '', "
                "title TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, updated_at REAL NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE groups (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at REAL NOT NULL)"
            )
            connection.execute(
                "INSERT INTO sessions (id, state, updated_at) VALUES (?, ?, ?)",
                ("session-1", '{"messages": []}', 30.0),
            )
            connection.execute(
                "INSERT INTO session_meta (session_id, group_id, title, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("session-1", "group-1", "保留的会话", 10.0, 20.0),
            )
            connection.execute(
                "INSERT INTO groups (id, name, created_at) VALUES (?, ?, ?)",
                ("group-1", "待删除分组", 10.0),
            )
            connection.commit()
            connection.close()

            manager = SessionManager(db_path)
            manager.close()

            connection = sqlite3.connect(db_path)
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            meta_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(session_meta)").fetchall()
            }
            metadata = connection.execute(
                "SELECT session_id, title, created_at, updated_at FROM session_meta"
            ).fetchone()
            session = connection.execute(
                "SELECT id, state, updated_at FROM sessions"
            ).fetchone()
            connection.close()

            self.assertNotIn("groups", tables)
            self.assertNotIn("group_id", meta_columns)
            self.assertEqual(metadata, ("session-1", "保留的会话", 10.0, 20.0))
            self.assertEqual(session, ("session-1", '{"messages": []}', 30.0))


if __name__ == "__main__":
    unittest.main()
