"""RunSnapshot 纯逻辑：证据分类 / partial report / 旧会话 turn 还原。"""

import unittest

from secgo.runtime.snapshot import classify_tool_evidence
from secgo.web.server import _legacy_turns_from_messages


class EvidenceClassificationTests(unittest.TestCase):
    def test_skill_list_and_execute_bash_are_not_evidence(self):
        self.assertIsNone(classify_tool_evidence("skill_list", {"success": True, "output": "x"}))
        self.assertIsNone(classify_tool_evidence("skill_read", {"success": True, "output": "x"}))
        self.assertIsNone(classify_tool_evidence("execute_bash", {"success": True, "output": "x"}))
        self.assertIsNone(classify_tool_evidence("handoff_to_agent", {"success": True, "output": "x"}))

    def test_web_search_is_evidence_but_mcp_prefix_is_not_auto_evidence(self):
        record = classify_tool_evidence("web_search", {"success": True, "output": "found"})
        self.assertIsNotNone(record)
        self.assertEqual(record["source"], "web_search")
        # mcp_ 前缀不再自动成为证据：工具来源 ≠ 证据成立
        self.assertIsNone(classify_tool_evidence("mcp_scan", {"success": True, "output": "found"}))
        self.assertIsNone(classify_tool_evidence("mcp_brave_search", {"success": True, "output": "[medium] XSS"}))

    def test_empty_output_is_not_evidence(self):
        self.assertIsNone(classify_tool_evidence("web_search", {"success": True, "output": "(no output)"}))

    def test_no_search_results_is_not_evidence(self):
        self.assertIsNone(classify_tool_evidence("web_search", {"success": True, "output": "No search results found."}))

    def test_tool_error_is_not_evidence(self):
        self.assertIsNone(classify_tool_evidence("web_search", {"success": False, "error": "connection failed"}))
        self.assertIsNone(classify_tool_evidence("port_scan", {"success": False, "error": "permission denied"}))

    def test_valid_port_scan_is_evidence(self):
        record = classify_tool_evidence("port_scan", {"success": True, "output": "80/tcp open\n443/tcp open"})
        self.assertIsNotNone(record)
        self.assertEqual(record["source"], "port_scan")


class EvidenceDedupeTests(unittest.TestCase):
    def test_snapshot_dedupes_same_evidence(self):
        from secgo.runtime.snapshot import RunSnapshotRecorder
        recorder = RunSnapshotRecorder("s1", run_id="r1")
        recorder.apply("engine:evidence", {"evidence": {"id": "e1", "source": "port_scan", "summary": "80/tcp open"}})
        recorder.apply("engine:evidence", {"evidence": {"id": "e2", "source": "port_scan", "summary": "80/tcp open"}})
        self.assertEqual(len(recorder.evidence), 1)

    def test_decision_reason_enters_snapshot_and_timeline(self):
        from secgo.runtime.snapshot import RunSnapshotRecorder
        recorder = RunSnapshotRecorder("s1", run_id="r1")
        decision = {
            "id": "d1", "timestamp": 1000, "trigger": "tool_failure", "trigger_detail": "nmap 连续失败",
            "observation": "原计划: x", "candidates": [], "selected": "", "reason": "换策略", "rejected": [],
        }
        recorder.apply("decision:reason", {"decision": decision})
        self.assertEqual(len(recorder.decisions), 1)
        self.assertEqual(recorder.to_dict()["decisions"][0]["id"], "d1")
        self.assertTrue(any(item["kind"] == "finding" and "策略调整" in item["title"] for item in recorder.timeline))


class LegacyTurnsTests(unittest.TestCase):
    def test_recovers_user_question_and_strips_attachment_prompt(self):
        turns = _legacy_turns_from_messages([
            {"role": "user", "content": "[用户附件]\n附件 1：\n- evidence_id: x\n\n用户问题：\n这是一个杂项题，你能找到flag吗"},
            {"role": "assistant", "content": "A1"},
        ])
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["userMessage"]["text"], "这是一个杂项题，你能找到flag吗")
        self.assertEqual(turns[0]["assistantAnswer"], "A1")

    def test_skips_internal_engine_prompts(self):
        turns = _legacy_turns_from_messages([
            {"role": "user", "content": "检查 example.com"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "[系统提示：你已执行 10 步。]"},
            {"role": "user", "content": "[Handoff from Planner]: 执行侦察"},
            {"role": "user", "content": "[工具结果 execute_bash]: 443 open"},
            {"role": "user", "content": "第二个问题"},
        ])
        self.assertEqual([t["userMessage"]["text"] for t in turns], ["检查 example.com", "第二个问题"])


if __name__ == "__main__":
    unittest.main()
