"""RePlan 决策状态机测试。"""

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from secgo.kernel.plan_state import (
    PlanState, ReplanDetector, FailedAttempt, CandidateStrategy, DecisionRecord,
    REPLAN_TRIGGER_TOOL_CONSECUTIVE_FAILURES,
    REPLAN_TRIGGER_SAME_TOOL_REPEAT,
    REPLAN_TRIGGER_NO_PROGRESS_STEPS,
)


class ReplanDetectorTests(unittest.TestCase):
    def setUp(self):
        self.detector = ReplanDetector()

    def test_detects_consecutive_failures(self):
        self.detector.record_tool_call("nmap", False, 1)
        self.detector.record_tool_call("nmap", False, 2)
        trigger = self.detector.check(3, "operator")
        self.assertIsNotNone(trigger)
        self.assertEqual(trigger["trigger"], "tool_failure")

    def test_detects_repeated_same_tool(self):
        for i in range(REPLAN_TRIGGER_SAME_TOOL_REPEAT):
            self.detector.record_tool_call("gobuster", False, i + 1)
        trigger = self.detector.check(4, "operator")
        self.assertIsNotNone(trigger)
        self.assertEqual(trigger["trigger"], "repeated_calls")

    def test_detects_no_progress(self):
        self.detector.record_tool_call("nmap", True, 1)  # 最后一次成功在第 1 步
        # 记录少量失败（total_failures < 5 避免 excessive_failures），不同工具避免 repeated_calls
        self.detector.record_tool_call("tool_a", False, 16)
        self.detector.record_tool_call("tool_b", False, 17)
        self.detector.record_tool_call("tool_c", False, 18)
        self.detector.record_tool_call("tool_d", False, 19)
        # total_failures=4 < 5, no repeated_calls, last_finding_step=1
        # step=20: steps_since_finding=19 >= 15 → no_progress 应触发
        trigger = self.detector.check(20, "operator")
        self.assertIsNotNone(trigger)
        self.assertEqual(trigger["trigger"], "no_progress")

    def test_no_trigger_when_all_successful(self):
        for i in range(10):
            self.detector.record_tool_call("nmap", True, i + 1)
        self.assertIsNone(self.detector.check(11, "operator"))

    def test_handoff_resets_no_progress_counter(self):
        self.detector.record_tool_call("nmap", True, 1)
        self.detector.record_handoff(5)  # 第 5 步 handoff，重置 last_finding_step=5
        self.detector.record_tool_call("nmap", False, 6)  # 仅 1 次失败
        # 距离上次 handoff 只有 1 步（step=6, last_finding_step=5, diff=1），不够触发 no_progress
        # 且 consecutive_failures=1 低于阈值 2
        self.assertIsNone(self.detector.check(6, "operator"))


class PlanStateTests(unittest.TestCase):
    def setUp(self):
        self.plan = PlanState(goal="渗透测试 target.com")

    def test_initial_state(self):
        self.assertEqual(self.plan.goal, "渗透测试 target.com")
        self.assertEqual(self.plan.replan_count, 0)
        self.assertEqual(len(self.plan.decision_history), 0)

    def test_set_plan_and_criteria(self):
        self.plan.set_plan("1. 信息收集 2. 漏洞扫描", ["发现开放端口", "识别漏洞"])
        self.assertEqual(self.plan.current_plan, "1. 信息收集 2. 漏洞扫描")
        self.assertEqual(len(self.plan.success_criteria), 2)

    def test_add_failure(self):
        self.plan.add_failure("operator", "nmap", "Connection refused", step=5)
        self.assertEqual(len(self.plan.failed_attempts), 1)
        self.assertEqual(self.plan.failed_attempts[0].tool_name, "nmap")

    def test_trigger_replan_creates_decision(self):
        self.plan.set_plan("扫描 80 端口")
        decision = self.plan.trigger_replan(
            trigger="tool_failure",
            trigger_detail="nmap 连续 2 次失败",
            active_agent_id="operator",
        )
        self.assertEqual(self.plan.replan_count, 1)
        self.assertEqual(len(self.plan.decision_history), 1)
        self.assertIsInstance(decision, DecisionRecord)
        self.assertEqual(decision.trigger, "tool_failure")
        self.assertTrue(len(decision.candidates) >= 2)
        self.assertTrue(decision.selected.startswith("c"))

    def test_multiple_replans_increment_count(self):
        self.plan.trigger_replan("tool_failure", "fail1", "operator")
        self.plan.trigger_replan("no_progress", "no progress 1", "operator")
        self.assertEqual(self.plan.replan_count, 2)
        self.assertEqual(len(self.plan.decision_history), 2)

    def test_generate_candidates_for_tool_failure(self):
        candidates = self.plan.generate_candidates("tool_failure", "nmap failed", "operator")
        self.assertTrue(len(candidates) >= 2)
        # 工具失败时，候选 A 应该建议换替代工具
        self.assertIn("更换替代工具", candidates[0].description)

    def test_generate_candidates_for_no_progress(self):
        candidates = self.plan.generate_candidates("no_progress", "15 steps no progress", "operator")
        self.assertTrue(len(candidates) >= 2)
        # 无进展时，候选 A 应该建议回溯
        self.assertIn("回溯方案", candidates[0].description)

    def test_serialization_roundtrip(self):
        self.plan.set_plan("测试计划", ["标准1", "标准2"])
        self.plan.add_failure("op", "nmap", "err", step=1)
        self.plan.trigger_replan("tool_failure", "fail", "op")
        serialized = self.plan.to_serializable()
        restored = PlanState.from_serializable(serialized)
        self.assertEqual(restored.goal, self.plan.goal)
        self.assertEqual(restored.current_plan, self.plan.current_plan)
        self.assertEqual(restored.replan_count, self.plan.replan_count)
        self.assertEqual(len(restored.decision_history), len(self.plan.decision_history))
        self.assertEqual(restored.decision_history[0].trigger, "tool_failure")


class ReplanLoopSafetyTests(unittest.TestCase):
    """RePlan 后触发状态必须重置，且能区分原计划/新计划。"""

    def test_reset_after_replan_clears_trigger_state(self):
        detector = ReplanDetector()
        detector.record_tool_call("nmap", False, 1)
        detector.record_tool_call("nmap", False, 2)
        self.assertIsNotNone(detector.check(3, "operator"))
        detector.reset_after_replan()
        self.assertIsNone(detector.check(4, "operator"))
        self.assertEqual(detector._total_failures, 0)
        self.assertEqual(detector._consecutive_failures, 0)

    def test_trigger_replan_distinguishes_original_and_new_plan(self):
        plan = PlanState(goal="t")
        plan.set_plan("原计划：扫描 80 端口")
        plan.add_failure("operator", "nmap", "err", step=1)
        decision = plan.trigger_replan("tool_failure", "nmap 连续失败", "operator")
        # 原计划保留在 decision.observation，current_plan 只保存新计划
        self.assertIn("原计划：扫描 80 端口", decision.observation)
        self.assertIn("[RePlan #1]", plan.current_plan)
        self.assertNotEqual(plan.current_plan, "原计划：扫描 80 端口")

    def test_replan_count_guards_max(self):
        from secgo.kernel.plan_state import MAX_REPLANS
        self.assertGreater(MAX_REPLANS, 0)

    def test_exhaustion_notice_flag_roundtrip(self):
        plan = PlanState(goal="t")
        self.assertFalse(plan.exhaustion_notice_injected)
        plan.exhaustion_notice_injected = True
        restored = PlanState.from_serializable(plan.to_serializable())
        self.assertTrue(restored.exhaustion_notice_injected)


class StrategySelectionTests(unittest.TestCase):
    def test_select_strategy_avoids_recently_failed_tool(self):
        plan = PlanState(goal="t")
        candidates = [
            CandidateStrategy("c-a", "更换替代工具", "operator", ["nmap"], "low", "x"),
            CandidateStrategy("c-b", "切换 Agent 重新规划", "planner", [], "medium", "x"),
        ]
        selected, rejected = plan.select_strategy(candidates, "tool_failure", "operator", failed_tool="nmap")
        self.assertEqual(selected.id, "c-b")  # 避开刚失败的 nmap
        self.assertEqual(len(rejected), 1)

    def test_select_strategy_varies_with_trigger(self):
        plan = PlanState(goal="t")
        candidates = [
            CandidateStrategy("c-a", "继续当前 Agent 换工具", "operator", ["nmap"], "low", "x"),
            CandidateStrategy("c-b", "切到 Planner 重新规划", "planner", [], "medium", "x"),
        ]
        # excessive_failures：倾向回退 Planner
        selected_exc, _ = plan.select_strategy(candidates, "excessive_failures", "operator")
        self.assertEqual(selected_exc.id, "c-b")
        # 普通 tool_failure（无失败工具记录）：低风险同 Agent 优先，稳定 tie-break 取第一个
        selected_tf, _ = plan.select_strategy(candidates, "tool_failure", "operator")
        self.assertEqual(selected_tf.id, "c-a")


if __name__ == "__main__":
    unittest.main()