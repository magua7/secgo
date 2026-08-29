"""MCP 客户端管理：stdio/sse 多服务器聚合，工具名 mcp_<server>_<tool> 全局唯一。"""

import asyncio
from typing import Any, Dict, List, Optional

from ..config.config import McpServerConfig

MCP_CALL_TIMEOUT_S = 60

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.sse import sse_client
    from mcp.client.stdio import stdio_client

    _MCP_AVAILABLE = True
except Exception:  # mcp 包缺失或版本不兼容
    _MCP_AVAILABLE = False


def _tool_input_schema(tool: Any) -> Dict[str, Any]:
    """兼容 mcp 1.x（inputSchema）与 2.x（input_schema）的 Tool 属性名。"""
    for attr in ("input_schema", "inputSchema"):
        value = getattr(tool, attr, None)
        if isinstance(value, dict):
            return value
    return {}


class McpClientManager:
    def __init__(self) -> None:
        self._servers: Dict[str, Dict[str, Any]] = {}
        self._tool_routes: Dict[str, Dict[str, str]] = {}
        self._available = _MCP_AVAILABLE

    async def initialize_all(self, servers: List[McpServerConfig]) -> None:
        if self._servers:
            await self.close_all()
        results = await asyncio.gather(
            *[self._init_one(server, i) for i, server in enumerate(servers)],
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                print(f"[MCP] 初始化服务器失败: {result}")

    async def _init_one(self, server: McpServerConfig, index: int) -> None:
        if not self._available:
            print("[MCP] mcp 包未安装，跳过 MCP 服务器初始化")
            return
        server_name = server.name or f"server{index}"
        if server_name in self._servers:
            return

        transport_cm: Any = None
        try:
            # sse_client / stdio_client 返回的是 async context manager，
            # 必须先进入上下文才能拿到 (read, write) 流——不能直接解包。
            if server.type == "sse" and server.url:
                transport_cm = sse_client(server.url)
            else:
                params = StdioServerParameters(
                    command=server.command,
                    args=list(server.args),
                    env=dict(server.env) if server.env else None,
                )
                transport_cm = stdio_client(params)
            read, write = await transport_cm.__aenter__()

            session_cm: Any = ClientSession(read, write)
            session = await session_cm.__aenter__()
            try:
                await session.initialize()
            except Exception:
                await session_cm.__aexit__(None, None, None)
                raise

            tools_result = await session.list_tools()
            tools = [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "input_schema": _tool_input_schema(t),
                }
                for t in tools_result.tools
            ]

            self._servers[server_name] = {
                "session": session,
                "session_cm": session_cm,
                "transport_cm": transport_cm,
                "tools": tools,
            }
            for tool in tools:
                self._tool_routes[f"mcp_{server_name}_{tool['name']}"] = {
                    "server": server_name,
                    "original": tool["name"],
                }
            print(f'[MCP] 已连接服务器 "{server_name}"（{len(tools)} 个工具）')
        except Exception as err:
            # 连接中途失败：回滚已进入的 transport 上下文，避免泄漏子进程/连接
            if transport_cm is not None:
                try:
                    await transport_cm.__aexit__(None, None, None)
                except Exception:
                    pass
            print(f'[MCP] 连接服务器 "{server_name}" 失败: {err}')

    def get_tools(self) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for name, entry in self._servers.items():
            for tool in entry["tools"]:
                result.append({
                    "name": f"mcp_{name}_{tool['name']}",
                    "description": tool["description"],
                    "input_schema": tool["input_schema"],
                })
        return result

    async def call_tool(self, full_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        route = self._tool_routes.get(full_name)
        if route is None:
            return {"success": False, "error": "MCP tool not found"}
        entry = self._servers.get(route["server"])
        if entry is None:
            return {"success": False, "error": "MCP server not connected"}
        session: ClientSession = entry["session"]

        try:
            result = await asyncio.wait_for(
                session.call_tool(route["original"], arguments=args),
                timeout=MCP_CALL_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": f'MCP tool "{full_name}" timed out after {MCP_CALL_TIMEOUT_S}s',
            }
        except Exception as err:
            return {"success": False, "error": f"MCP tool call failed: {err}"}

        parts: List[str] = []
        for content in result.content or []:
            if getattr(content, "type", None) == "text":
                parts.append(getattr(content, "text", ""))
        return {"success": True, "output": "\n".join(parts) or "(no output)"}

    def is_connected(self) -> bool:
        return len(self._servers) > 0

    async def close_all(self) -> None:
        entries = list(self._servers.values())
        self._servers.clear()
        self._tool_routes.clear()
        for entry in entries:
            # 退出顺序：先会话、再传输（stdio/sse 的子进程与连接随 transport 关闭）
            session_cm = entry.get("session_cm")
            if session_cm is not None:
                try:
                    await session_cm.__aexit__(None, None, None)
                except Exception:
                    pass
            transport_cm = entry.get("transport_cm")
            if transport_cm is not None:
                try:
                    await transport_cm.__aexit__(None, None, None)
                except Exception:
                    pass


mcp_client = McpClientManager()


class McpLifecycleManager:
    def __init__(self) -> None:
        self._servers: Optional[List[McpServerConfig]] = None
        self._running = False
        self._health_task: Optional[asyncio.Task] = None

    async def start(self, servers: List[McpServerConfig]) -> None:
        self._servers = servers
        self._running = True
        await mcp_client.initialize_all(servers)
        self._stop_health_check()
        self._health_task = asyncio.create_task(self._health_loop())

    async def _health_loop(self) -> None:
        while self._running:
            await asyncio.sleep(30)
            if not self._running or self._servers is None:
                break
            if not mcp_client.is_connected():
                try:
                    await mcp_client.initialize_all(self._servers)
                except Exception:
                    pass

    def _stop_health_check(self) -> None:
        if self._health_task is not None:
            self._health_task.cancel()
            self._health_task = None

    async def shutdown(self) -> None:
        self._running = False
        self._stop_health_check()
        await mcp_client.close_all()
        self._servers = None

    def is_running(self) -> bool:
        return self._running


mcp_lifecycle = McpLifecycleManager()
