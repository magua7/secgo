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
            budget=SimpleNamespace(maxTokensPerSession=100_000, maxStepsPerTask=20),
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

        response = await server.api_cancel_session(session_id)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(handoff_engine.is_engine_awaiting_input(session_id))
        with self.assertRaises(asyncio.CancelledError):
            await waiting
        channel = server._channels[session_id]
        self.assertEqual(channel.ring[-1][1], "engine:end")
        self.assertEqual(channel.ring[-1][2]["reason"], "cancelled")
        server._channels.pop(session_id, None)
