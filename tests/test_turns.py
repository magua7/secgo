"""多轮 Turn 持久化：每个 Turn 独立 execution snapshot，新 Turn 不覆盖旧 Turn。"""

import os
import tempfile
import unittest
from unittest.mock import patch

from secgo.runtime import turn_manager
from secgo.runtime.eventbus import event_bus
from secgo.runtime.session import SessionManager


def _emit(event_name: str, data: dict) -> None:
    payload = dict(data)
    payload.setdefault("session_id", "s1")
    event_bus.emit(event_name, payload)


class TurnPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "test.db")
        self.manager = SessionManager(self.db)
        self.manager.save_state("s1", {"messages": []})
        self._patch = patch.object(turn_manager, "resolve_session_db_path", return_value=self.db)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        for session_id in list(turn_manager._active_turns):
            recorder = turn_manager._active_turns.pop(session_id)
            recorder.finalize()
        turn_manager._active_turns.clear()
        self.manager.close()

    def test_turn_recorder_finalizes_completed_on_engine_end(self):
        self.manager.create_turn("s1", "t1", 1, {"text": "你好", "attachments": []}, "direct_response", "running")
        turn_manager.start_turn("s1", "t1")
        _emit("engine:start", {})
        _emit("agent:thinking", {"agent_id": "builder"})
        _emit("engine:text", {"agent_id": "builder", "text": "# 最终报告"})
        _emit("engine:end", {"reason": "completed", "total_steps": 3})
        turn = self.manager.list_turns("s1")[0]
        self.assertEqual(turn["status"], "completed")
        self.assertEqual(turn["assistantAnswer"], "# 最终报告")
        self.assertEqual(turn["execution"]["status"], "completed")

    def test_direct_response_turn_finalizes_on_awaiting_input(self):
        self.manager.create_turn("s1", "t1", 1, {"text": "你好", "attachments": []}, "direct_response", "running")
        turn_manager.start_turn("s1", "t1")
        _emit("engine:text", {"agent_id": "planner", "text": "你好，我是 SEC-GO。"})
        _emit("engine:awaiting_input", {"agent_id": "planner", "message": "你好，我是 SEC-GO。"})
        turn = self.manager.list_turns("s1")[0]
        self.assertEqual(turn["status"], "awaiting_user")
        self.assertEqual(turn["kind"], "direct_response")
        self.assertEqual(turn["assistantAnswer"], "你好，我是 SEC-GO。")

    def test_stopped_turn_persists_partial_report(self):
        self.manager.create_turn("s1", "t1", 1, {"text": "task", "attachments": []}, "direct_response", "running")
        turn_manager.start_turn("s1", "t1")
        _emit("tool:stream-start", {"tool_name": "port_scan", "args": {}})
        _emit("tool:stream-end", {"tool_name": "port_scan", "result": "443 open"})
        turn_manager.finalize_active_turn("s1", reason="cancelled")
        turn = self.manager.list_turns("s1")[0]
        self.assertEqual(turn["status"], "stopped")
        self.assertEqual(turn["kind"], "agent_task")
        self.assertIn("终止原因", turn["execution"]["partial_report"])

    def test_new_turn_does_not_overwrite_previous_turn(self):
        # Turn 1：direct response 完成
        self.manager.create_turn("s1", "t1", 1, {"text": "你好", "attachments": []}, "direct_response", "running")
        turn_manager.start_turn("s1", "t1")
        _emit("engine:text", {"agent_id": "planner", "text": "A1"})
        _emit("engine:awaiting_input", {"message": "A1"})

        # Turn 2：agent task stopped（带 partial report）
        self.manager.create_turn("s1", "t2", 2, {"text": "task2", "attachments": []}, "direct_response", "running")
        turn_manager.start_turn("s1", "t2")
        _emit("tool:stream-start", {"tool_name": "port_scan", "args": {}})
        _emit("tool:stream-end", {"tool_name": "port_scan", "result": "443 open"})
        turn_manager.finalize_active_turn("s1", reason="cancelled")

        # Turn 3：agent task running
        self.manager.create_turn("s1", "t3", 3, {"text": "task3", "attachments": []}, "direct_response", "running")
        turn_manager.start_turn("s1", "t3")
        _emit("engine:text", {"agent_id": "operator", "text": "正在执行"})

        turns = self.manager.list_turns("s1")
        self.assertEqual([t["sequence"] for t in turns], [1, 2, 3])
        self.assertEqual(turns[0]["assistantAnswer"], "A1")
        self.assertEqual(turns[0]["status"], "awaiting_user")
        # Turn 2 的 stopped 快照不能被 Turn 3 覆盖
        self.assertEqual(turns[1]["status"], "stopped")
        self.assertIn("终止原因", turns[1]["execution"]["partial_report"])
        self.assertEqual(turns[1]["userMessage"]["text"], "task2")
        # Turn 3 仍是 running（未收尾）
        self.assertEqual(turns[2]["status"], "running")
        self.assertEqual(turns[2]["userMessage"]["text"], "task3")

    def test_session_status_is_latest_turn_status(self):
        self.manager.create_turn("s1", "t1", 1, {"text": "你好", "attachments": []}, "direct_response", "running")
        self.manager.create_turn("s1", "t2", 2, {"text": "task", "attachments": []}, "agent_task", "stopped")
        self.assertEqual(self.manager.get_session_status("s1"), "stopped")

    def test_legacy_turns_fallback(self):
        # 无 conversation_turns 的旧 session 由 server 层还原（见 test_snapshot_persistence）
        self.assertEqual(self.manager.list_turns("s1"), [])


if __name__ == "__main__":
    unittest.main()
