import asyncio
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from secgo.kernel import handoff_engine
from secgo.model.provider import StreamAgentResponse
from secgo.tools.registry import get_tools_for_agent
from secgo.web import server


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


class AgentLoopTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        handoff_engine._input_resolvers.clear()
        self.events = []
        self.config = SimpleNamespace(
            budget=SimpleNamespace(maxTokensPerSession=100_000, maxStepsPerTask=20, maxReplansPerRun=3),
            llm=SimpleNamespace(subscriptions={"coding": SimpleNamespace()}, agents={}),
            context=SimpleNamespace(toolOutputMaxTokens=2000),
        )

    async def _run(self, responses, initial=None, execute_tool=None, session_id="session-1"):
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
            result = await handoff_engine.run_engine("test", session_id)
        return result, manager, stream, tool

    def _completed_events(self):
        return [data for event, data in self.events if event == "engine:end" and data.get("reason") == "completed"]

    def test_task_complete_is_only_exposed_to_planner(self):
        for agent_id in ("research", "builder", "operator"):
            self.assertNotIn("task_complete", {tool.name for tool in get_tools_for_agent(agent_id)})
        self.assertIn("task_complete", {tool.name for tool in get_tools_for_agent("planner")})

    async def test_planner_completes_with_final_text_and_task_complete(self):
        result, _, _, tool = await self._run([
            _response("完整最终研判结果", [_call("task_complete", {"summary": "研判完成"})]),
        ])
        self.assertEqual(result["reason"], "completed")
        self.assertEqual(self._completed_events()[0]["summary"], "研判完成")
        tool.assert_not_awaited()
        self.assertFalse(handoff_engine.is_engine_awaiting_input("session-1"))

    async def test_planner_plain_text_waits_for_user_input(self):
        task = asyncio.create_task(self._run([_response("请提供目标 URL。")]))
        for _ in range(20):
            if handoff_engine.is_engine_awaiting_input("session-1"):
                break
            await asyncio.sleep(0)
        self.assertTrue(handoff_engine.is_engine_awaiting_input("session-1"))
        self.assertTrue(any(event == "engine:awaiting_input" for event, _ in self.events))
        handoff_engine.provide_user_input("session-1", "https://example.com")
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_research_handoff_to_planner(self):
        initial = {"activeAgentId": "research", "messages": [], "stepCount": 0}
        result, _, _, _ = await self._run([
            _response("研究摘要", [_call("handoff_to_agent", {"target_agent_id": "planner", "reason": "研究完成", "task": "继续决策"})]),
            _response("最终结果", [_call("task_complete", {"summary": "完成"})]),
        ], initial)
        self.assertEqual(result["reason"], "completed")
        self.assertTrue(any(event == "agent:switch" and data["to_agent_id"] == "planner" for event, data in self.events))

    async def test_builder_handoff_to_operator(self):
        initial = {"activeAgentId": "builder", "messages": [], "stepCount": 0}
        result, _, _, _ = await self._run([
            _response("构建完成", [_call("handoff_to_agent", {"target_agent_id": "operator", "reason": "待验证", "task": "验证脚本"})]),
            _response("验证完成", [_call("handoff_to_agent", {"target_agent_id": "planner", "reason": "验证完成", "task": "汇总"})]),
            _response("最终结果", [_call("task_complete", {"summary": "完成"})]),
        ], initial)
        self.assertEqual(result["reason"], "completed")
        switches = [data["to_agent_id"] for event, data in self.events if event == "agent:switch"]
        self.assertEqual(switches, ["operator", "planner"])

    async def test_operator_handoff_to_planner(self):
        initial = {"activeAgentId": "operator", "messages": [], "stepCount": 0}
        result, _, _, _ = await self._run([
            _response("执行摘要", [_call("handoff_to_agent", {"target_agent_id": "planner", "reason": "执行完成", "task": "汇总"})]),
            _response("最终结果", [_call("task_complete", {"summary": "完成"})]),
        ], initial)
        self.assertEqual(result["reason"], "completed")
        self.assertTrue(any(event == "agent:switch" and data["to_agent_id"] == "planner" for event, data in self.events))

    async def test_non_planner_task_complete_is_rejected(self):
        initial = {"activeAgentId": "research", "messages": [], "stepCount": 0}
        result, _, stream, tool = await self._run([
            _response("错误完成", [_call("task_complete", {"summary": "不应完成"})]),
            _response("返回 Planner", [_call("handoff_to_agent", {"target_agent_id": "planner", "reason": "权限纠正", "task": "继续"})]),
            _response("最终结果", [_call("task_complete", {"summary": "完成"})]),
        ], initial)
        self.assertEqual(result["reason"], "completed")
        self.assertEqual(len(self._completed_events()), 1)
        second_messages = stream.await_args_list[1].args[1]
        self.assertTrue(any("Agent Permission Error" in str(message.get("content")) for message in second_messages))
        tool.assert_not_awaited()

    async def test_handoff_and_task_complete_are_both_rejected(self):
        calls = [
            _call("handoff_to_agent", {"target_agent_id": "operator", "reason": "冲突", "task": "执行"}, "handoff"),
            _call("task_complete", {"summary": "冲突"}, "complete"),
        ]
        result, _, stream, tool = await self._run([
            _response("冲突", calls),
            _response("最终结果", [_call("task_complete", {"summary": "完成"})]),
        ])
        self.assertEqual(result["reason"], "completed")
        self.assertFalse(any(event == "agent:switch" for event, _ in self.events))
        self.assertTrue(any("Agent Protocol Error" in str(message.get("content")) for message in stream.await_args_list[1].args[1]))
        tool.assert_not_awaited()

    async def test_business_and_control_tools_are_all_rejected(self):
        calls = [
            _call("skill_list", {}, "business"),
            _call("handoff_to_agent", {"target_agent_id": "operator", "reason": "冲突", "task": "执行"}, "handoff"),
        ]
        result, _, _, tool = await self._run([
            _response("冲突", calls),
            _response("最终结果", [_call("task_complete", {"summary": "完成"})]),
        ])
        self.assertEqual(result["reason"], "completed")
        self.assertFalse(any(event == "agent:switch" for event, _ in self.events))
        tool.assert_not_awaited()

    async def test_multiple_business_tools_all_execute(self):
        tool = AsyncMock(side_effect=[
            {"success": True, "output": "skills"},
            {"success": True, "output": "skill body"},
        ])
        result, _, _, _ = await self._run([
            _response("加载技能", [_call("skill_list", {}, "one"), _call("skill_read", {"name": "hack"}, "two")]),
            _response("最终结果", [_call("task_complete", {"summary": "完成"})]),
        ], execute_tool=tool)
        self.assertEqual(result["reason"], "completed")
        self.assertEqual([call.args[0] for call in tool.await_args_list], ["skill_list", "skill_read"])

    async def test_replan_exhaustion_notice_is_injected_once(self):
        """达到 max_replans 后，收尾指引只注入一次，后续触发条件被静默吞掉。"""
        from secgo.kernel.plan_state import MAX_REPLANS, PlanState

        self.config.budget.maxReplansPerRun = MAX_REPLANS
        plan = PlanState(goal="t")
        plan.replan_count = MAX_REPLANS
        # 预置检测器：进入主循环第一次 check 即触发 tool_failure
        plan.detector.record_tool_call("nmap", False, 0)
        plan.detector.record_tool_call("nmap", False, 0)
        initial = {
            "activeAgentId": "planner",
            "messages": [],
            "stepCount": 1,
            "planState": plan.to_serializable(),
        }
        tool = AsyncMock(return_value={"success": False, "error": "boom"})
        result, _, stream, _ = await self._run([
            _response("", [_call("nmap", {}, "f1")]),
            _response("", [_call("nmap", {}, "f2")]),
            _response("最终结果", [_call("task_complete", {"summary": "完成"})]),
        ], initial, execute_tool=tool)
        self.assertEqual(result["reason"], "completed")
        exhausted_events = [
            data for event, data in self.events
            if event == "decision:reason" and data["decision"]["trigger"] == "replan_exhausted"
        ]
        self.assertEqual(len(exhausted_events), 1)
        # 注入一次后该提示常驻对话历史；任何一次 LLM 调用里都不应出现第二条
        for call in stream.await_args_list:
            contents = [message.get("content") for message in call.args[1] if isinstance(message.get("content"), str)]
            self.assertEqual(sum("已达最大重规划次数" in content for content in contents), 1)

    async def test_max_steps_continuation_renews_run_budget(self):
        """max_steps 是 Run 级额度：同 Session「继续」后重新获得步数额度，且不丢失上下文。"""
        self.config.budget.maxStepsPerTask = 3
        manager = _MemorySessionManager(None)
        tool = AsyncMock(return_value={"success": True, "output": "ok"})
        # 每个响应都调用业务工具，使循环持续消耗步数（不完成、不挂起输入）
        responses = [_response("", [_call("skill_list", {}, f"s{i}")]) for i in range(6)]
        stream = AsyncMock(side_effect=responses)
        with (
            patch.object(handoff_engine, "get_config", return_value=self.config),
            patch.object(handoff_engine, "SessionManager", return_value=manager),
            patch.object(handoff_engine, "resolve_session_db_path", return_value=":memory:"),
            patch.object(handoff_engine, "stream_agent_response", stream),
            patch.object(handoff_engine, "execute_tool", tool),
            patch.object(handoff_engine.event_bus, "emit", Mock()),
            patch.object(handoff_engine.mcp_client, "is_connected", return_value=False),
        ):
            result1 = await handoff_engine.run_engine("task", "s-cont")
            calls_after_first = stream.await_count
            # 模拟 server 层续聊：把「继续」追加进 engine messages 后再启动第二个 Run
            saved = manager.load_state("s-cont")
            msgs = list(saved.get("messages") or [])
            msgs.append({"role": "user", "content": "继续"})
            saved["messages"] = msgs
            manager.save_state("s-cont", saved)
            result2 = await handoff_engine.run_engine("继续", "s-cont")
            calls_after_second = stream.await_count

        self.assertEqual(result1["reason"], "max_steps")
        self.assertEqual(result1["total_steps"], 3)
        self.assertEqual(result2["reason"], "max_steps")
        self.assertEqual(result2["total_steps"], 6)
        # 第二次确实重新调用 LLM，而非立刻 max_steps 退出
        self.assertGreater(calls_after_second, calls_after_first)
        persisted = manager.load_state("s-cont")
        self.assertEqual(persisted["stepCount"], 6)
        user_contents = [m.get("content") for m in persisted["messages"] if m.get("role") == "user"]
        self.assertTrue(any(isinstance(c, str) and "task" in c for c in user_contents))
        self.assertTrue(any(isinstance(c, str) and "继续" in c for c in user_contents))


class InputResolverTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        handoff_engine._input_resolvers.clear()

    async def asyncTearDown(self):
        for session_id in list(handoff_engine._input_resolvers):
            handoff_engine.cancel_waiting_input(session_id)
        await asyncio.sleep(0)

    async def test_two_sessions_resume_independently(self):
        waiting_a = asyncio.create_task(handoff_engine._wait_for_user_input("a"))
        waiting_b = asyncio.create_task(handoff_engine._wait_for_user_input("b"))
        await asyncio.sleep(0)
        self.assertTrue(handoff_engine.provide_user_input("a", "hello"))
        self.assertEqual(await waiting_a, "hello")
        self.assertTrue(handoff_engine.is_engine_awaiting_input("b"))
        self.assertFalse(waiting_b.done())
        handoff_engine.cancel_waiting_input("b")
        with self.assertRaises(asyncio.CancelledError):
            await waiting_b
        self.assertFalse(handoff_engine.is_engine_awaiting_input("b"))

    async def test_cancel_waiting_session_cleans_resolver_and_emits_cancelled(self):
        session_id = "cancel-session"
        waiting = asyncio.create_task(handoff_engine._wait_for_user_input(session_id))
        await asyncio.sleep(0)
        server._channels.pop(session_id, None)
        server._tasks.pop(session_id, None)

        events = []
        def _capture(data):
            events.append(data)
        server.event_bus.on("engine:end", _capture)

        response = await server.api_cancel_session(session_id)

        server.event_bus.off("engine:end", _capture)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(handoff_engine.is_engine_awaiting_input(session_id))
        with self.assertRaises(asyncio.CancelledError):
            await waiting
        self.assertTrue(any(
            event.get("session_id") == session_id and event.get("reason") == "cancelled"
            for event in events
        ))


class _FakeTask:
    def __init__(self, done=False):
        self._done = done

    def done(self):
        return self._done


class SessionBusyGuardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        server._channels.pop("s-busy", None)
        server._channels.pop("s-busy-api", None)
        server._awaiting_sessions.discard("s-busy")
        server._awaiting_sessions.discard("s-busy-api")

    def tearDown(self):
        server._tasks.pop("s-busy", None)
        server._tasks.pop("s-busy-api", None)
        server._channels.pop("s-busy", None)
        server._channels.pop("s-busy-api", None)

    def test_busy_when_running_and_not_awaiting(self):
        server._tasks["s-busy"] = _FakeTask(done=False)
        with patch.object(server, "is_engine_awaiting_input", return_value=False):
            self.assertTrue(server._session_busy("s-busy"))

    def test_not_busy_when_task_done(self):
        server._tasks["s-busy"] = _FakeTask(done=True)
        with patch.object(server, "is_engine_awaiting_input", return_value=False):
            self.assertFalse(server._session_busy("s-busy"))

    def test_not_busy_when_awaiting_continuation(self):
        server._tasks["s-busy"] = _FakeTask(done=False)
        with patch.object(server, "is_engine_awaiting_input", return_value=True):
            self.assertFalse(server._session_busy("s-busy"))

    async def test_api_chat_rejects_second_independent_run_with_409(self):
        import json as _json
        server._tasks["s-busy-api"] = _FakeTask(done=False)

        class _Req:
            async def json(self):
                return {"message": "task2", "sessionId": "s-busy-api"}

        with patch.object(server, "is_engine_awaiting_input", return_value=False):
            resp = await server.api_chat(_Req(), None)
        self.assertEqual(resp.status_code, 409)
        body = _json.loads(resp.body)
        self.assertEqual(body["code"], "SESSION_BUSY")
        self.assertIn("正在执行", body["message"])
        # _tasks 仍指向原来的 run（未被覆盖/清理）
        self.assertIsInstance(server._tasks["s-busy-api"], _FakeTask)
