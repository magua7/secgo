from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from secgo.runtime.session import SessionManager


def _state(title: str) -> dict:
    return {"messages": [{"role": "user", "content": title}], "stepCount": 0}


class SessionLimitTests(unittest.TestCase):
    def test_writes_keep_only_the_20_most_recent_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = SessionManager(Path(temp_dir) / "sessions.db")

            for number in range(1, 22):
                manager.save_state(f"session-{number:02d}", _state(f"会话 {number}"))

            session_ids = {session["id"] for session in manager.list_sessions()}
            evicted_meta = manager.get_meta("session-01")
            manager.close()

            self.assertEqual(len(session_ids), 20)
            self.assertNotIn("session-01", session_ids)
            self.assertIn("session-21", session_ids)
            self.assertIsNone(evicted_meta)

    def test_updating_an_old_session_makes_it_recent_again(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = SessionManager(Path(temp_dir) / "sessions.db")
            for number in range(1, 21):
                manager.save_state(f"session-{number:02d}", _state(f"会话 {number}"))

            manager.save_state("session-01", _state("刚刚继续的会话"))
            manager.save_state("session-21", _state("最新会话"))

            session_ids = {session["id"] for session in manager.list_sessions()}
            manager.close()

            self.assertEqual(len(session_ids), 20)
            self.assertIn("session-01", session_ids)
            self.assertNotIn("session-02", session_ids)

    def test_startup_trims_an_existing_database_to_20_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "sessions.db"
            connection = sqlite3.connect(db_path)
            connection.execute(
                "CREATE TABLE sessions (id TEXT PRIMARY KEY, state TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE session_meta (session_id TEXT PRIMARY KEY, title TEXT, "
                "created_at INTEGER, updated_at INTEGER)"
            )
            for number in range(1, 24):
                session_id = f"session-{number:02d}"
                connection.execute(
                    "INSERT INTO sessions (id, state) VALUES (?, ?)",
                    (session_id, json.dumps(_state(f"会话 {number}"), ensure_ascii=False)),
                )
                connection.execute(
                    "INSERT INTO session_meta "
                    "(session_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (session_id, f"会话 {number}", number, number),
                )
            connection.commit()
            connection.close()

            manager = SessionManager(db_path)
            session_ids = {session["id"] for session in manager.list_sessions()}
            manager.close()

            self.assertEqual(
                session_ids,
                {f"session-{number:02d}" for number in range(4, 24)},
            )


if __name__ == "__main__":
    unittest.main()
