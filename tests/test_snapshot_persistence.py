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

    def test_web_search_and_mcp_are_evidence(self):
        record = classify_tool_evidence("web_search", {"success": True, "output": "found"})
        self.assertIsNotNone(record)
        self.assertEqual(record["source"], "web_search")
        self.assertIsNotNone(classify_tool_evidence("mcp_scan", {"success": True, "output": "found"}))

    def test_empty_output_is_not_evidence(self):
        self.assertIsNone(classify_tool_evidence("web_search", {"success": True, "output": "(no output)"}))


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
