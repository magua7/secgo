"""RunSnapshot 纯逻辑：证据分类 / partial report / 旧会话 turn 还原。"""

import unittest

from secgo.runtime.snapshot import (
    RunSnapshotRecorder,
    build_evidence_records,
    classify_tool_evidence,
)
from secgo.web.server import _legacy_turns_from_messages


COOKIE_CTF_OUTPUT = (
    "HTTP/1.1 200 OK\n"
    "You are logged in as an admin user!\n"
    "Flag: CTF{cookie_injection_is_fun}"
)


class EvidenceClassificationTests(unittest.TestCase):
    def test_skill_list_and_execute_bash_are_not_evidence(self):
        # 普通输出（无高价值信号）不因工具名自动成为证据
        self.assertIsNone(classify_tool_evidence("skill_list", {"success": True, "output": "x"}))
        self.assertIsNone(classify_tool_evidence("skill_read", {"success": True, "output": "x"}))
        self.assertIsNone(classify_tool_evidence("execute_bash", {"success": True, "output": "x"}))
        self.assertIsNone(classify_tool_evidence("handoff_to_agent", {"success": True, "output": "x"}))

    def test_web_search_generic_result_is_not_evidence(self):
        """web_search 是证据候选而非天然可信来源：普通网页内容不得进入关键证据。"""
        self.assertIsNone(classify_tool_evidence("web_search", {"success": True, "output": "found"}))
        self.assertIsNone(classify_tool_evidence("web_search", {
            "success": True,
            "output": (
                "Apache HTTP Server 官方网站：产品介绍、功能特性与下载页面。"
                "普通技术文档与官网介绍不构成关键证据。 https://httpd.apache.org/"
            ),
        }))

    def test_web_search_mcp_prefix_is_still_not_auto_evidence(self):
        # mcp_ 前缀不自动成为证据：工具来源 ≠ 证据成立；内容命中安全信号才算
        self.assertIsNone(classify_tool_evidence("mcp_scan", {"success": True, "output": "found"}))

    def test_web_search_cve_intel_is_evidence(self):
        """明确 CVE + 目标组件版本匹配的漏洞情报 → 允许进入关键证据。"""
        record = classify_tool_evidence("web_search", {
            "success": True,
            "output": (
                "CVE-2021-41773：Apache HTTP Server 2.4.49 路径遍历漏洞，"
                "与当前目标组件版本明确匹配，官方已发布安全公告。"
            ),
        })
        self.assertIsNotNone(record)
        self.assertEqual(record["source"], "web_search")
        self.assertEqual(record["metadata"]["signal"], "cve_intel")

    def test_web_search_exploit_advisory_is_evidence(self):
        """exploit / advisory / PoC 等明确攻击指标 → 允许进入关键证据。"""
        record = classify_tool_evidence("web_search", {
            "success": True,
            "output": (
                "Security advisory: public exploit available for the target component, "
                "PoC published as EDB-50383."
            ),
        })
        self.assertIsNotNone(record)
        self.assertEqual(record["source"], "web_search")
        self.assertEqual(record["metadata"]["signal"], "exploit_intel")

    def test_dns_lookup_plain_result_is_still_evidence(self):
        """dns_lookup 保持可信来源：明确解析结果继续进入关键证据。"""
        record = classify_tool_evidence("dns_lookup", {
            "success": True,
            "output": "example.com. 300 IN A 93.184.216.34",
        })
        self.assertIsNotNone(record)
        self.assertEqual(record["source"], "dns_lookup")
        self.assertEqual(record["metadata"]["signal"], "generic_fact")

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


class ExecuteBashEvidenceTests(unittest.TestCase):
    """验收场景：execute_bash 拿到 Flag 必须生成强证据（不允许报告引用 Flag 而 Evidence=0）。"""

    def test_execute_bash_with_flag_is_confirmed_evidence(self):
        record = classify_tool_evidence(
            "execute_bash",
            {"success": True, "output": COOKIE_CTF_OUTPUT},
        )
        self.assertIsNotNone(record)
        self.assertEqual(record["source"], "execute_bash")
        self.assertIn("CTF{cookie_injection_is_fun}", record["summary"])
        self.assertEqual(record["confidence"], "confirmed")
        self.assertEqual(record["metadata"]["dedupe_key"], "flag:ctf{cookie_injection_is_fun}")

    def test_cookie_scenario_yields_two_distinct_records(self):
        records = build_evidence_records(
            "execute_bash",
            {"success": True, "output": COOKIE_CTF_OUTPUT},
        )
        kinds = [r["metadata"]["signal"] for r in records]
        # Cookie 权限绕过成功 + Flag 获取成功，两类证据同时成立
        self.assertIn("auth_privilege", kinds)
        self.assertIn("flag", kinds)
        self.assertEqual(len({r["metadata"]["dedupe_key"] for r in records}), len(records))

    def test_execute_bash_plain_ls_is_not_evidence(self):
        self.assertIsNone(
            classify_tool_evidence("execute_bash", {"success": True, "output": "README.md\nsrc\ntests"})
        )

    def test_execute_bash_timeout_is_not_evidence(self):
        self.assertIsNone(
            classify_tool_evidence("execute_bash", {"success": False, "error": "Command timed out after 10s."})
        )


class McpEvidenceTests(unittest.TestCase):
    def test_plain_mcp_success_output_is_not_auto_evidence(self):
        self.assertIsNone(
            classify_tool_evidence("mcp_browser_navigate", {"success": True, "output": "Opened https://target.com homepage"})
        )

    def test_mcp_security_critical_result_is_evidence(self):
        record = classify_tool_evidence(
            "mcp_brave_search",
            {"success": True, "output": "[high] SQL Injection at http://target/api?id=1 — injection verified with payload"},
        )
        self.assertIsNotNone(record)
        self.assertEqual(record["source"], "mcp_brave_search")
        self.assertTrue(record["source"].startswith("mcp_"))


class McpRegressionTests(unittest.TestCase):
    """防止旧 Gate 语义回归：mcp 前缀/普通输出继续被拒。"""

    def test_mcp_medium_xss_without_verification_stays_out(self):
        self.assertIsNone(classify_tool_evidence("mcp_brave_search", {"success": True, "output": "[medium] XSS"}))


class EvidenceDedupeUpgradeTests(unittest.TestCase):
    def test_same_flag_verified_twice_keeps_single_card(self):
        recorder = RunSnapshotRecorder("s1", run_id="r1")
        first = classify_tool_evidence("execute_bash", {"success": True, "output": COOKIE_CTF_OUTPUT})
        second = classify_tool_evidence(
            "mcp_http_fetch",
            {"success": True, "output": "GET /admin\n\nWelcome back!\nCTF{cookie_injection_is_fun}\n(done)"},
        )
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertNotEqual(first["summary"], second["summary"])  # 摘要不同，旧规则拦不住
        for record in (first, second):
            recorder.apply("engine:evidence", {"evidence": record})
        self.assertEqual(len(recorder.evidence), 1)

    def test_distinct_signals_are_not_merged(self):
        recorder = RunSnapshotRecorder("s1", run_id="r1")
        for record in build_evidence_records("execute_bash", {"success": True, "output": COOKIE_CTF_OUTPUT}):
            recorder.apply("engine:evidence", {"evidence": record})
        self.assertEqual(len(recorder.evidence), 2)


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
