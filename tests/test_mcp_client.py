"""MCP 接入链路测试：真实 stdio 子进程端到端 + 引擎分发集成（mock）。

曾经的真实缺陷（已修复，此处作为回归用例）：
- sse_client/stdio_client 返回 async context manager，直接解包会抛
  "cannot unpack non-iterable _AsyncGeneratorContextManager"，导致 MCP 从未连接成功；
- mcp 1.x 工具属性为 inputSchema，2.x 为 input_schema，硬编码任一都会断列工具。
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from secgo.config.config import McpServerConfig
from secgo.tools import mcp_client as mcp_client_mod
from secgo.tools.executor import check_permission, execute_tool
from secgo.tools.mcp_client import McpClientManager, mcp_client

_SERVER_SOURCE = textwrap.dedent(
    """
    import anyio
    import mcp.types as types
    from mcp.server.lowlevel import Server

    server = Server("test")

    async def list_tools(ctx, params):
        return types.ListToolsResult(tools=[
            types.Tool(name="echo", description="Echo text back.",
                       inputSchema={"type": "object",
                                    "properties": {"text": {"type": "string"}},
                                    "required": ["text"]}),
            types.Tool(name="add", description="Add two integers.",
                       inputSchema={"type": "object",
                                    "properties": {"a": {"type": "integer"},
                                                   "b": {"type": "integer"}},
                                    "required": ["a", "b"]}),
        ])

    async def call_tool(ctx, params):
        args = dict(params.arguments or {})
        if params.name == "echo":
            text = types.TextContent(type="text", text=f"echo: {args.get('text')}")
        elif params.name == "add":
            text = types.TextContent(type="text", text=str(int(args.get("a", 0)) + int(args.get("b", 0))))
        else:
            raise ValueError(f"unknown tool: {params.name}")
        return types.CallToolResult(content=[text])

    server.add_request_handler("tools/list", types.PaginatedRequestParams, list_tools)
    server.add_request_handler("tools/call", types.CallToolRequestParams, call_tool)

    async def main():
        from mcp.server.stdio import stdio_server
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    anyio.run(main)
    """
)


def _mcp_installed() -> bool:
    return mcp_client_mod._MCP_AVAILABLE


@unittest.skipUnless(_mcp_installed(), "mcp 包未安装，跳过真实子进程端到端测试")
class McpRealStdioEndToEndTests(unittest.IsolatedAsyncioTestCase):
    """用真实 MCP stdio 子进程验证：连接 → 列工具 → 调用 → 关闭。"""

    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        server_path = Path(self._tmp.name) / "mcp_server.py"
        server_path.write_text(_SERVER_SOURCE, encoding="utf-8")
        self.manager = McpClientManager()
        self.config = McpServerConfig(
            name="test", type="stdio", command=sys.executable, args=[str(server_path)]
        )

    async def asyncTearDown(self):
        await self.manager.close_all()
        self._tmp.cleanup()

    async def test_connect_list_call_close_full_chain(self):
        await self.manager.initialize_all([self.config])
        self.assertTrue(self.manager.is_connected())

        tools = self.manager.get_tools()
        names = {t["name"] for t in tools}
        self.assertEqual(names, {"mcp_test_echo", "mcp_test_add"})
        # 工具 schema 必须透传（兼容 1.x/2.x 属性名）
        echo = next(t for t in tools if t["name"] == "mcp_test_echo")
        self.assertEqual(echo["input_schema"].get("type"), "object")
        self.assertIn("text", echo["input_schema"].get("properties", {}))

        result = await self.manager.call_tool("mcp_test_echo", {"text": "hello-secgo"})
        self.assertTrue(result["success"])
        self.assertEqual(result["output"], "echo: hello-secgo")

        result = await self.manager.call_tool("mcp_test_add", {"a": 2, "b": 3})
        self.assertTrue(result["success"])
        self.assertEqual(result["output"], "5")

    async def test_unknown_tool_and_server_yield_clean_errors(self):
        await self.manager.initialize_all([self.config])
        missing_tool = await self.manager.call_tool("mcp_test_nonexistent", {})
        self.assertFalse(missing_tool["success"])
        self.assertEqual(missing_tool["error"], "MCP tool not found")

        missing_server = await self.manager.call_tool("mcp_ghost_echo", {})
        self.assertFalse(missing_server["success"])

        await self.manager.close_all()
        self.assertFalse(self.manager.is_connected())
        # 关闭后路由表一并清空：任何调用都应拿到干净的失败而不是异常
        after_close = await self.manager.call_tool("mcp_test_echo", {"text": "x"})
        self.assertFalse(after_close["success"])
        self.assertIn("not found", after_close["error"])

    async def test_initialize_all_is_idempotent_and_recovers(self):
        await self.manager.initialize_all([self.config])
        first_tools = {t["name"] for t in self.manager.get_tools()}
        # 重复初始化：先关旧连接再重建，不产生重复路由
        await self.manager.initialize_all([self.config])
        second_tools = {t["name"] for t in self.manager.get_tools()}
        self.assertEqual(first_tools, second_tools)
        self.assertEqual(len(self.manager.get_tools()), 2)
        result = await self.manager.call_tool("mcp_test_add", {"a": 10, "b": 5})
        self.assertEqual(result["output"], "15")


class McpEngineIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """不依赖外部进程：验证引擎/执行器侧的 MCP 分发与权限语义。"""

    def _fake_tools(self):
        return [
            {"name": "mcp_sec_nmap_scan", "description": "run nmap scan against target",
             "input_schema": {"type": "object"}},
            {"name": "mcp_sec_fetch_url", "description": "fetch a web url and read content",
             "input_schema": {"type": "object"}},
        ]

    async def test_execute_tool_routes_mcp_prefix_to_client(self):
        called = {}

        async def fake_call(name, args):
            called["name"] = name
            return {"success": True, "output": "mcp result"}

        with patch.object(mcp_client, "call_tool", side_effect=fake_call):
            result = await execute_tool("mcp_sec_nmap_scan", {"target": "127.0.0.1"}, "s1", "operator")

        self.assertTrue(result["success"])
        self.assertEqual(result["output"], "mcp result")
        self.assertEqual(called["name"], "mcp_sec_nmap_scan")

    def test_mcp_tools_allowed_for_every_agent(self):
        for agent in ("planner", "research", "builder", "operator"):
            self.assertTrue(check_permission("mcp_any_tool", agent))

    async def test_mcp_tools_reach_agent_tool_set_when_connected(self):
        from secgo.kernel import handoff_engine
        from secgo.tools.registry import build_tool_set, get_tools_for_agent

        tools = build_tool_set(get_tools_for_agent("operator"))
        with (
            patch.object(mcp_client_mod.mcp_client, "get_tools", return_value=self._fake_tools()),
            patch.object(handoff_engine.mcp_client, "is_connected", return_value=True),
            patch.object(handoff_engine.mcp_client, "get_tools", return_value=self._fake_tools()),
        ):
            merged = tools + handoff_engine._mcp_tools_for_agent("operator", "scan target")
        names = {t["name"] for t in merged}
        self.assertIn("mcp_sec_nmap_scan", names)
        self.assertIn("mcp_sec_fetch_url", names)
        self.assertIn("execute_bash", names)


if __name__ == "__main__":
    unittest.main()
