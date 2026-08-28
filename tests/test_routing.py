"""Agent 路由专项测试：Planner 主动路由 Builder/Research + RePlan 候选 + 轻量路由提示。

覆盖目标：
- 简单扫描 → Planner → Operator（不注入 Builder/Research 提示，不强制多 Agent）；
- CVE 情报 → Planner 应收到 Research 路由建议；
- 编写 PoC / Misc 图像 LSB → Planner 应收到 Builder 路由建议；
- Operator 发现复杂脚本需求 → Operator → Planner → Builder；
- Research 返回公开 PoC → Planner 可继续交给 Operator / Builder；
- RePlan 候选必须包含 Builder，且任务语境需要脚本时倾向 Builder。
"""

import asyncio
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from secgo.kernel import handoff_engine
from secgo.kernel.plan_state import PlanState
from secgo.model.provider import StreamAgentResponse


def _response(text="", calls=None):
    calls = calls or []
    native_calls = [
        {
            "id": call.get("id", f"call-{index}"),
            "type": "function",
            "function": {"name": call["name"], "arguments": call.get("arguments", {})},
        }
        for index, call in enumerate(calls)
    ]
    return StreamAgentResponse(
        text=text,
        tool_calls=[
            {"id": call["id"], "name": call["function"]["name"], "arguments": call["function"]["arguments"]}
            for call in native_calls
        ],
        response_messages=[{"role": "assistant", "content": text, "tool_calls": native_calls}],
    )


def _call(name, arguments=None, call_id=None):
    return {"id": call_id or f"call-{name}", "name": name, "arguments": arguments or {}}


class _MemorySessionManager:
    def __init__(self, initial=None):
        self.state = copy.deepcopy(initial)

    def load_state(self, _session_id):
        return copy.deepcopy(self.state)

    def save_state(self, _session_id, state):
        self.state = copy.deepcopy(state)

    def close(self):
        pass


class RoutingHintUnitTests(unittest.TestCase):
    """轻量路由提示（纯启发式，无 LLM 调用）单元测试。"""

    def test_lsb_image_task_hints_builder(self):
        hint = handoff_engine.build_routing_hint(["提取图片 LSB 中隐藏的数据"])
        self.assertIn("Builder", hint)
        self.assertIn("脚本", hint)

    def test_poc_script_task_hints_builder(self):
        hint = handoff_engine.build_routing_hint(["编写一个 XXE 检测 PoC"])
        self.assertIn("Builder", hint)

    def test_cve_task_hints_research(self):
        hint = handoff_engine.build_routing_hint(["查询 CVE-2024-1234 的公开漏洞情报"])
        self.assertIn("Research", hint)
        self.assertNotIn("Builder", hint)

    def test_unknown_framework_task_hints_research(self):
        hint = handoff_engine.build_routing_hint(["这个框架怎么用，查询技术文档"])
        self.assertIn("Research", hint)

    def test_simple_scan_task_has_no_hint(self):
        hint = handoff_engine.build_routing_hint(["扫描目标 192.168.1.1 的开放端口"])
        self.assertEqual(hint, "")

    def test_builder_wins_when_both_signals_present(self):
        # builder 信号（提取/图片/lsb/数据）强于 research 信号（cve/文档）
        hint = handoff_engine.build_routing_hint(["提取图片 LSB 数据，参考 CVE 文档"])
        self.assertIn("Builder", hint)

    def test_empty_inputs_no_hint(self):
        self.assertEqual(handoff_engine.build_routing_hint([]), "")
        self.assertEqual(handoff_engine.build_routing_hint([None, ""]), "")


class ReplanRoutingTests(unittest.TestCase):
    """RePlan 候选必须包含 Builder，且脚本语境下倾向 Builder。"""

    def test_tool_failure_candidates_include_builder(self):
        plan = PlanState(goal="t")
        candidates = plan.generate_candidates("tool_failure", "nmap failed", "operator")
        self.assertTrue(any(c.target_agent == "builder" for c in candidates))
        # 首个候选仍保持「更换替代工具」（兼容既有行为）
        self.assertIn("更换替代工具", candidates[0].description)

    def test_repeated_calls_candidates_include_research_and_builder(self):
        plan = PlanState(goal="t")
        candidates = plan.generate_candidates("repeated_calls", "gobuster repeat fail", "operator")
        targets = {c.target_agent for c in candidates}
        self.assertIn("research", targets)
        self.assertIn("builder", targets)

    def test_no_progress_candidates_include_builder(self):
        plan = PlanState(goal="t")
        candidates = plan.generate_candidates("no_progress", "15 steps no progress", "operator")
        self.assertTrue(any(c.target_agent == "builder" for c in candidates))
        # 首个候选仍保持「回溯方案」
        self.assertIn("回溯方案", candidates[0].description)

    def test_script_need_replan_selects_builder(self):
        plan = PlanState(goal="编写解码脚本提取数据")
        plan.set_plan("手工尝试解码")
        decision = plan.trigger_replan("tool_failure", "现成工具连续失败", "operator")
        selected = next(c for c in decision.candidates if c.id == decision.selected)
        self.assertEqual(selected.target_agent, "builder")

    def test_plain_replan_does_not_default_to_builder(self):
        plan = PlanState(goal="扫描目标端口")
        plan.set_plan("nmap 扫描")
        decision = plan.trigger_replan("tool_failure", "nmap 连续失败", "operator")
        selected = next(c for c in decision.candidates if c.id == decision.selected)
        self.assertNotEqual(selected.target_agent, "builder")

    def test_no_progress_replan_keeps_research_candidate(self):
        plan = PlanState(goal="目标信息收集")
        decision = plan.trigger_replan("no_progress", "15 步无进展", "operator")
        targets = {c.target_agent for c in decision.candidates}
        self.assertIn("research", targets)
        self.assertIn("builder", targets)


class AgentRoutingLoopTests(unittest.IsolatedAsyncioTestCase):
    """引擎级路由路径测试：模拟 LLM 决策，验证 handoff 链与路由提示注入。"""

    def setUp(self):
        handoff_engine._input_resolvers.clear()
        self.events = []
        self.config = SimpleNamespace(
            budget=SimpleNamespace(maxTokensPerRun=100_000, maxStepsPerRun=20, maxReplansPerRun=3),
            llm=SimpleNamespace(subscriptions={"coding": SimpleNamespace()}, agents={}),
            context=SimpleNamespace(toolOutputMaxTokens=2000),
        )

    async def _run(self, responses, initial=None, execute_tool=None, session_id="routing-session", user_input="test"):
        manager = _MemorySessionManager(initial)
        stream = AsyncMock(side_effect=responses)
        tool = execute_tool or AsyncMock(return_value={"success": True, "output": "ok"})
        emitter = Mock(side_effect=lambda event, data: self.events.append((event, data)))
        with (
            patch.object(handoff_engine, "get_config", return_value=self.config),
            patch.object(handoff_engine, "SessionManager", return_value=manager),
            patch.object(handoff_engine, "resolve_session_db_path", return_value=":memory:"),
            patch.object(handoff_engine, "stream_agent_response", stream),
            patch.object(handoff_engine, "execute_tool", tool),
            patch.object(handoff_engine.event_bus, "emit", emitter),
            patch.object(handoff_engine.mcp_client, "is_connected", return_value=False),
        ):
            result = await handoff_engine.run_engine(user_input, session_id)
        return result, manager, stream, tool

    def _switch_targets(self):
        return [data["to_agent_id"] for event, data in self.events if event == "agent:switch"]

    def _planner_prompts(self, stream):
        return [call.args[3] or "" for call in stream.await_args_list]

    async def test_simple_scan_routes_operator_without_builder_research(self):
        """简单扫描：Planner → Operator → Planner，不注入 Builder/Research 提示。"""
        result, _, stream, _ = await self._run([
            _response("制定计划", [_call("handoff_to_agent", {"target_agent_id": "operator", "reason": "扫描目标开放端口", "task": "扫描 192.168.1.1 端口"})]),
            _response("执行完成", [_call("handoff_to_agent", {"target_agent_id": "planner", "reason": "扫描完成", "task": "汇总"})]),
            _response("最终结果", [_call("task_complete", {"summary": "完成"})]),
        ], user_input="扫描目标 192.168.1.1 的开放端口")
        self.assertEqual(result["reason"], "completed")
        self.assertEqual(self._switch_targets(), ["operator", "planner"])
        self.assertTrue(all("路由建议" not in p for p in self._planner_prompts(stream)))

    async def test_cve_task_injects_research_hint_and_routes_research(self):
        """CVE 情报：Planner 收到 Research 路由建议，并路由到 Research。"""
        result, _, stream, _ = await self._run([
            _response("规划", [_call("handoff_to_agent", {"target_agent_id": "research", "reason": "需要查询目标版本公开漏洞情报", "task": "查 CVE-2024-1234"})]),
            _response("情报", [_call("handoff_to_agent", {"target_agent_id": "planner", "reason": "已完成情报检索", "task": "总结"})]),
            _response("最终", [_call("task_complete", {"summary": "完成"})]),
        ], user_input="查询 CVE-2024-1234 的公开漏洞情报")
        self.assertEqual(result["reason"], "completed")
        self.assertTrue(any(data["to_agent_id"] == "research" for event, data in self.events if event == "agent:switch"))
        self.assertTrue(any("Research" in p and "路由建议" in p for p in self._planner_prompts(stream)))

    async def test_lsb_image_task_injects_builder_hint_and_flows_builder_operator(self):
        """Misc 图像 LSB：Planner 收到 Builder 路由建议，路径为 Builder → Operator 验证。"""
        result, _, stream, _ = await self._run([
            _response("规划", [_call("handoff_to_agent", {"target_agent_id": "builder", "reason": "需要构建自定义解码脚本", "task": "写 LSB 提取脚本"})]),
            _response("构建", [_call("handoff_to_agent", {"target_agent_id": "operator", "reason": "待执行验证", "task": "运行脚本"})]),
            _response("验证", [_call("handoff_to_agent", {"target_agent_id": "planner", "reason": "验证完成", "task": "汇总"})]),
            _response("最终", [_call("task_complete", {"summary": "完成"})]),
        ], user_input="提取图片 LSB 中隐藏的数据")
        self.assertEqual(result["reason"], "completed")
        self.assertEqual(self._switch_targets(), ["builder", "operator", "planner"])
        self.assertTrue(any("Builder" in p and "路由建议" in p for p in self._planner_prompts(stream)))

    async def test_operator_script_need_returns_to_planner_then_builder(self):
        """Operator 发现复杂脚本需求：Operator → Planner → Builder → Operator。"""
        result, _, _, _ = await self._run([
            _response("需要脚本", [_call("handoff_to_agent", {"target_agent_id": "planner", "reason": "需要编写解码脚本", "task": "需要 Builder 构建解码脚本"})]),
            _response("规划", [_call("handoff_to_agent", {"target_agent_id": "builder", "reason": "需要构建自定义解码脚本", "task": "写脚本"})]),
            _response("构建", [_call("handoff_to_agent", {"target_agent_id": "operator", "reason": "待执行验证", "task": "运行脚本"})]),
            _response("验证", [_call("handoff_to_agent", {"target_agent_id": "planner", "reason": "验证完成", "task": "汇总"})]),
            _response("最终", [_call("task_complete", {"summary": "完成"})]),
        ], initial={"activeAgentId": "operator", "messages": [], "stepCount": 0}, user_input="继续")
        self.assertEqual(result["reason"], "completed")
        self.assertEqual(self._switch_targets(), ["planner", "builder", "operator", "planner"])

    async def test_research_returns_public_poc_planner_chooses_operator(self):
        """Research 返回公开 PoC → Planner 决定交给 Operator 直接验证。"""
        result, _, _, _ = await self._run([
            _response("情报", [_call("handoff_to_agent", {"target_agent_id": "planner", "reason": "已找到公开 PoC", "task": "CVE-2024-1234 有公开 PoC"})]),
            _response("规划", [_call("handoff_to_agent", {"target_agent_id": "operator", "reason": "验证公开 PoC", "task": "执行 PoC"})]),
            _response("验证", [_call("handoff_to_agent", {"target_agent_id": "planner", "reason": "验证完成", "task": "汇总"})]),
            _response("最终", [_call("task_complete", {"summary": "完成"})]),
        ], initial={"activeAgentId": "research", "messages": [], "stepCount": 0}, user_input="继续")
        self.assertEqual(result["reason"], "completed")
        self.assertEqual(self._switch_targets(), ["planner", "operator", "planner"])

    async def test_replan_force_switch_to_builder_when_script_need(self):
        """operator 连续失败 + 任务语境需要脚本 → RePlan 强制切到 Builder。"""
        failing = AsyncMock(return_value={"success": False, "error": "boom"})
        responses = [
            _response("规划", [_call("handoff_to_agent", {"target_agent_id": "operator", "reason": "探测", "task": "探测目标"})]),
            _response("", [_call("nmap", {}, "f1")]),
            _response("", [_call("nmap", {}, "f2")]),
            _response("构建", [_call("handoff_to_agent", {"target_agent_id": "operator", "reason": "待执行验证", "task": "运行脚本"})]),
            _response("验证", [_call("handoff_to_agent", {"target_agent_id": "planner", "reason": "验证完成", "task": "汇总"})]),
            _response("最终", [_call("task_complete", {"summary": "完成"})]),
        ]
        result, _, _, _ = await self._run(
            responses, execute_tool=failing, user_input="编写解码脚本提取数据，目标 127.0.0.1"
        )
        self.assertEqual(result["reason"], "completed")
        replan_switches = [
            data for event, data in self.events
            if event == "agent:switch"
            and data.get("from_agent_id") == "operator"
            and data.get("to_agent_id") == "builder"
            and "RePlan" in data.get("reason", "")
        ]
        self.assertEqual(len(replan_switches), 1)

    async def test_simple_scan_never_forces_all_four_agents(self):
        """简单题：不得为测试强制四 Agent 全参与。"""
        result, _, stream, _ = await self._run([
            _response("制定计划", [_call("handoff_to_agent", {"target_agent_id": "operator", "reason": "扫描目标开放端口", "task": "扫描端口"})]),
            _response("执行完成", [_call("handoff_to_agent", {"target_agent_id": "planner", "reason": "扫描完成", "task": "汇总"})]),
            _response("最终结果", [_call("task_complete", {"summary": "完成"})]),
        ], user_input="扫描目标 192.168.1.1 的开放端口")
        self.assertEqual(result["reason"], "completed")
        participated = {
            data["agent_id"] for event, data in self.events
            if event == "agent:thinking"
        } | {"planner"}
        self.assertNotIn("research", participated)
        self.assertNotIn("builder", participated)


if __name__ == "__main__":
    unittest.main()
