"""Run / Turn / Session / Task 预算与续跑状态统一回归测试。

覆盖第三轮审查要点：
- RePlan 额度按 Run 重置（run_replan_count），且 total_replan_count 累计审计；
- exhaustion_notice_injected 是 Run 临时状态，不跨 Run 继承；
- detector 瞬态窗口不跨 Run 继承（避免「继续」瞬间误触发 RePlan）；
- 全局 Plan 只有 Planner 可更新；
- task_complete 后新任务只保留对话历史，重置执行控制状态。
"""

import asyncio
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from secgo.kernel import handoff_engine
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


def _fail_call(name, call_id=None):
    return _call(name, {}, call_id)


class _MemorySessionManager:
    def __init__(self, initial=None):
        self.state = copy.deepcopy(initial)

    def load_state(self, _session_id):
        return copy.deepcopy(self.state)

    def save_state(self, _session_id, state):
        self.state = copy.deepcopy(state)

    def close(self):
        pass


class BudgetContinuityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        handoff_engine._input_resolvers.clear()
        self.events = []

    def _config(self, max_replans=2, max_steps=20):
        return SimpleNamespace(
            budget=SimpleNamespace(maxTokensPerRun=100_000, maxStepsPerRun=max_steps, maxReplansPerRun=max_replans),
            llm=SimpleNamespace(subscriptions={"coding": SimpleNamespace()}, agents={}),
            context=SimpleNamespace(toolOutputMaxTokens=2000),
        )

    async def _run(self, responses, config, initial=None, execute_tool=None,
                   session_id="s-budget", manager=None, user_input="task"):
        if manager is None:
            manager = _MemorySessionManager(initial)
        stream = AsyncMock(side_effect=responses)
        tool = execute_tool or AsyncMock(return_value={"success": True, "output": "ok"})
        emitter = Mock(side_effect=lambda event, data: self.events.append((event, data)))
        with (
            patch.object(handoff_engine, "get_config", return_value=config),
            patch.object(handoff_engine, "SessionManager", return_value=manager),
            patch.object(handoff_engine, "resolve_session_db_path", return_value=":memory:"),
            patch.object(handoff_engine, "stream_agent_response", stream),
            patch.object(handoff_engine, "execute_tool", tool),
            patch.object(handoff_engine.event_bus, "emit", emitter),
            patch.object(handoff_engine.mcp_client, "is_connected", return_value=False),
        ):
            result = await handoff_engine.run_engine(user_input, session_id)
        return result, manager, stream

    def _replan_decisions(self):
        return [
            data for event, data in self.events
            if event == "decision:reason" and data["decision"]["trigger"] != "replan_exhausted"
        ]

    def _exhausted_decisions(self):
        return [
            data for event, data in self.events
            if event == "decision:reason" and data["decision"]["trigger"] == "replan_exhausted"
        ]

    async def test_replan_budget_renews_per_run_and_total_accumulates(self):
        """RePlan 额度按 Run 重置：Run1 用 2 次，Run2 仍能触发第 3 次且累计计数=3。"""
        config = self._config(max_replans=2, max_steps=6)
        failing_tool = AsyncMock(return_value={"success": False, "error": "boom"})

        # Run 1：2 次 RePlan 后耗尽步数（resumable 态，非 completed）
        run1 = [
            _response("", [_fail_call("probe", "f1")]),
            _response("", [_fail_call("probe", "f2")]),
            _response("", [_fail_call("probe", "f3")]),
            _response("", [_fail_call("probe", "f4")]),
            _response("", [_fail_call("probe", "f5")]),
            _response("", [_fail_call("probe", "f6")]),
        ]
        result1, manager, _ = await self._run(run1, config, execute_tool=failing_tool)
        self.assertEqual(result1["reason"], "max_steps")
        saved1 = manager.load_state("s-budget")
        self.assertEqual(saved1["planState"]["total_replan_count"], 2)
        self.assertEqual(len(self._replan_decisions()), 2)
        self.assertEqual(len(self._exhausted_decisions()), 0)

        # 模拟 server 层续聊：把「继续」补进 engine messages 后启动第二个 Run
        saved = manager.load_state("s-budget")
        msgs = list(saved.get("messages") or [])
        msgs.append({"role": "user", "content": "继续"})
        saved["messages"] = msgs
        manager.save_state("s-budget", saved)

        # Run 2：应先恢复干净额度，再真正触发 1 次 RePlan（若沿用旧计数则会被吞掉）
        self.events = []
        run2 = [
            _response("", [_fail_call("probe", "g1")]),
            _response("", [_fail_call("probe", "g2")]),
            _response("完成", [_call("task_complete", {"summary": "完成"})]),
        ]
        result2, manager, _ = await self._run(run2, config, execute_tool=failing_tool, manager=manager)
        self.assertEqual(result2["reason"], "completed")
        saved2 = manager.load_state("s-budget")
        # Run 级计数不落库（恒 0），累计计数跨 Run 连续：2 + 1 = 3
        self.assertEqual(saved2["planState"]["run_replan_count"], 0)
        self.assertEqual(saved2["planState"]["total_replan_count"], 3)
        # Run2 确实触发了 1 次真实 RePlan（额度重新获得，未被旧计数吞掉）
        self.assertEqual(len(self._replan_decisions()), 1)

    async def test_exhaustion_notice_does_not_carry_over(self):
        """第一 Run 注入的 exhaustion_notice 不跨 Run：新 Run 仍允许 RePlan。"""
        config = self._config(max_replans=2)
        failing_tool = AsyncMock(return_value={"success": False, "error": "boom"})
        # 模拟「上一 Run 已耗尽 + notice 已注入」的旧状态落库
        initial = {
            "activeAgentId": "planner",
            "messages": [],
            "stepCount": 4,
            "planState": {
                "goal": "t",
                "current_plan": "[RePlan #2] ...",
                "success_criteria": [],
                "failed_attempts": [],
                "replan_count": 2,
                "total_replan_count": 2,
                "decision_history": [],
                "exhaustion_notice_injected": True,
                "detector": {"consecutive_failures": 0, "total_failures": 0, "last_finding_step": 0},
            },
        }
        responses = [
            _response("", [_fail_call("probe", "h1")]),
            _response("", [_fail_call("probe", "h2")]),
            _response("完成", [_call("task_complete", {"summary": "完成"})]),
        ]
        result, manager, _ = await self._run(responses, config, initial=initial, execute_tool=failing_tool)
        self.assertEqual(result["reason"], "completed")
        # 新 Run 能真正触发 RePlan（notice 已重置），且不再注入「耗尽」提示
        self.assertEqual(len(self._replan_decisions()), 1)
        self.assertEqual(len(self._exhausted_decisions()), 0)

    async def test_new_run_does_not_instant_replan_from_stale_window(self):
        """上一 Run 尾部的连续失败瞬态不跨 Run：新 Run 第一步不得自动 RePlan。"""
        config = self._config(max_replans=2)
        initial = {
            "activeAgentId": "planner",
            "messages": [],
            "stepCount": 5,
            "planState": {
                "goal": "t",
                "current_plan": "p",
                "success_criteria": [],
                "failed_attempts": [],
                "replan_count": 0,
                "decision_history": [],
                "exhaustion_notice_injected": False,
                # 旧版本会把连续失败窗口持久化：新 Run 不应继承
                "detector": {"consecutive_failures": 2, "total_failures": 2, "last_finding_step": 3},
            },
        }
        responses = [_response("直接完成", [_call("task_complete", {"summary": "完成"})])]
        result, _, stream = await self._run(responses, config, initial=initial)
        self.assertEqual(result["reason"], "completed")
        # 第一步没有因为旧 transient counter 触发任何 RePlan
        self.assertEqual(len(self._replan_decisions()), 0)
        self.assertEqual(len(self._exhausted_decisions()), 0)
        first_messages = stream.await_args_list[0].args[1]
        self.assertFalse(any("[系统 RePlan 指令]" in str(m.get("content")) for m in first_messages))

    async def test_only_planner_updates_global_plan(self):
        """Research 输出 TODO 不得覆盖 Planner 全局计划；Planner 输出必须更新。"""
        config = self._config(max_replans=2)
        initial = {
            "activeAgentId": "research",
            "messages": [],
            "stepCount": 0,
            "planState": {
                "goal": "t",
                "current_plan": "PLANNER-ORIGINAL",
                "success_criteria": [],
                "failed_attempts": [],
                "replan_count": 0,
                "decision_history": [],
                "exhaustion_notice_injected": False,
                "detector": {},
            },
        }
        responses = [
            _response("- [ ] 研究本地 TODO step", [_call("skill_list", {}, "s1")]),
            _response("", [_call("handoff_to_agent", {"target_agent_id": "planner", "reason": "研究完成", "task": "汇总"})]),
            _response("- [ ] 全局步骤 A\n- [x] 全局步骤 B", [_call("task_complete", {"summary": "完成"})]),
        ]
        result, manager, _ = await self._run(responses, config, initial=initial)
        self.assertEqual(result["reason"], "completed")
        todo_events = [d for event, d in self.events if event == "todo:updated"]
        # 只有 Planner 的一次 TODO 更新，且标注 agent_id
        self.assertEqual(len(todo_events), 1)
        self.assertEqual(todo_events[0]["agent_id"], "planner")
        self.assertTrue(any("全局步骤 A" in t["text"] for t in todo_events[0]["todo_list"]))
        saved = manager.load_state("s-budget")
        plan = saved["planState"]
        # 全局计划被 Planner 覆盖，且不含 Research 的本地 TODO
        self.assertIn("全局步骤 A", plan["current_plan"])
        self.assertNotIn("研究本地 TODO", plan["current_plan"])
        self.assertNotIn("PLANNER-ORIGINAL", plan["current_plan"])

    async def test_completed_task_then_new_task_resets_control_state(self):
        """task_complete 后新任务：保留对话历史，重置 PlanState/detector/failed_attempts/TODO。"""
        config = self._config(max_replans=2)
        failing_tool = AsyncMock(return_value={"success": False, "error": "boom"})
        # Task A：失败一次后完成
        run_a = [
            _response("", [_fail_call("probe", "a1")]),
            _response("任务A完成 TASK-A-DONE", [_call("task_complete", {"summary": "TASK-A-DONE"})]),
        ]
        result_a, manager, _ = await self._run(run_a, config, execute_tool=failing_tool)
        self.assertEqual(result_a["reason"], "completed")
        saved_a = manager.load_state("s-budget")
        self.assertEqual(saved_a["completionSummary"], "TASK-A-DONE")
        self.assertEqual(len(saved_a["planState"]["failed_attempts"]), 1)

        # 模拟 server 层：追加新用户消息后启动新 Run
        self.events = []
        saved = manager.load_state("s-budget")
        msgs = list(saved.get("messages") or [])
        msgs.append({"role": "user", "content": "帮我分析目标B"})
        saved["messages"] = msgs
        manager.save_state("s-budget", saved)

        run_b = [
            _response("- [ ] B 步骤一", [_call("task_complete", {"summary": "TASK-B-DONE"})]),
        ]
        result_b, manager, _ = await self._run(run_b, config, manager=manager, user_input="帮我分析目标B")
        self.assertEqual(result_b["reason"], "completed")
        saved_b = manager.load_state("s-budget")
        plan = saved_b["planState"]
        # 控制状态重置为 Task B
        self.assertEqual(plan["goal"], "帮我分析目标B")
        self.assertEqual(plan["failed_attempts"], [])
        self.assertIn("B 步骤一", plan["current_plan"])
        self.assertTrue(any("B 步骤一" in (t.get("text") or "") for t in saved_b["todoList"]))
        # 对话历史保留（Task A 的完成结论仍在）
        contents = [str(m.get("content")) for m in saved_b["messages"]]
        self.assertTrue(any("TASK-A-DONE" in c for c in contents))


if __name__ == "__main__":
    unittest.main()
