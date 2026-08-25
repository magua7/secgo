"""交互命令处理（/skill /mcp /model /session 等，CLI 与 Web 共用）。"""

import asyncio
from typing import Any, Dict, List, Optional

from ..config.config import get_config
from ..runtime.session import SessionManager, resolve_session_db_path
from .agents import AGENT_REGISTRY
from .runtime_overrides import get_all_runtime_overrides, set_runtime_override
from .skill_loader import list_skills, read_skill, search_skills


# ── /skill ────────────────────────────────────────────────


def handle_skill_command(args: List[str]) -> str:
    if not args or args[0] == "help":
        return "\n".join([
            "/skill 子命令:",
            "  list          — 列出全部启用技能（名称 + 一句话描述）",
            "  <name>        — 显示指定技能全文",
            "  search <关键词> — 按名称/描述模糊搜索（top10）",
            "用法: /skill [list|<name>|search <关键词>]",
        ])

    sub = args[0]
    if sub == "list":
        skills = list_skills()
        if not skills:
            return "暂无可用 skill（检查 skill/ 目录或 SECGO_SKILLS_DIR 环境变量）"
        lines = [f"SEC-GO 安全技能库（启用 {len(skills)} 个）:"]
        for s in skills:
            lines.append(f"  - {s['name']} [{s['group']}] — {s['description']}")
        return "\n".join(lines)

    if sub == "search":
        keyword = " ".join(args[1:]).strip()
        if not keyword:
            return "用法: /skill search <关键词>"
        results = search_skills(keyword)
        if not results:
            return f'未找到与 "{keyword}" 匹配的技能'
        lines = [f'搜索 "{keyword}" 结果（{len(results)} 条）:']
        for s in results:
            marker = "" if s["enabled"] else " [未启用]"
            lines.append(f"  - {s['name']} [{s['group']}]{marker} — {s['description']}")
        return "\n".join(lines)

    # /skill <name>
    text = read_skill(sub)
    if text is None:
        return f"技能不存在: {sub}（用 /skill list 查看全部，或 /skill search <关键词> 搜索）"
    return text


# ── /mcp ──────────────────────────────────────────────────


async def handle_mcp_command(sub: Optional[str] = None) -> str:
    from ..tools.mcp_client import mcp_client, mcp_lifecycle

    if sub == "status":
        if mcp_client.is_connected():
            tools = mcp_client.get_tools()
            lines = [f"✓ MCP 已连接（{len(tools)} 个工具可用）"]
            if mcp_lifecycle.is_running():
                lines.append("  健康检查: 运行中")
            return "\n".join(lines)
        return "✗ MCP 未连接"
    if sub == "disconnect":
        await mcp_lifecycle.shutdown()
        return "✓ MCP 已断开"
    if sub == "reconnect":
        servers = get_config().mcp.servers
        if not servers:
            return "✗ 未配置 MCP 服务器，请先在 config/mcp.jsonc 中配置"
        print(f"正在重新连接 {len(servers)} 个 MCP 服务器...")
        try:
            await mcp_lifecycle.start(list(servers))
            return "✓ MCP 重连完成"
        except Exception as err:
            return f"✗ MCP 重连失败: {err}"
    if sub == "tools":
        tools = mcp_client.get_tools()
        if not tools:
            return "暂无可用 MCP 工具"
        lines = [f"可用 MCP 工具 ({len(tools)}):"]
        for tool in tools:
            lines.append(f"  - {tool['name']}: {tool['description'] or '(无描述)'}")
        return "\n".join(lines)
    return "MCP 子命令: status, disconnect, reconnect, tools\n用法: /mcp <子命令>"


# ── /model ────────────────────────────────────────────────


def handle_model_command(args: List[str]) -> str:
    config = get_config()
    sub_keys = list(config.llm.subscriptions.keys())
    agent_ids = list(AGENT_REGISTRY.keys())
    all_overrides = get_all_runtime_overrides()

    if not args:
        lines = ["当前模型配置:"]
        for agent_id in agent_ids:
            override = all_overrides.get(agent_id)
            config_override = config.llm.agents.get(agent_id)
            sub = (
                override.get("subscription")
                if override
                else (config_override.subscription if config_override else None)
            ) or "(默认)"
            model = (
                override.get("modelId")
                if override
                else (config_override.modelId if config_override else None)
            ) or "(默认)"
            sub_info = config.llm.subscriptions.get(sub)
            provider = sub_info.provider if sub_info else "未配置"
            is_overridden = " [运行时覆盖]" if override else ""
            lines.append(f"  {agent_id}: subscription={sub} ({provider}), model={model}{is_overridden}")
        lines.append("")
        lines.append(f"可用订阅: {', '.join(sub_keys) if sub_keys else '(无)'}")
        lines.append("用法: /model <agent> <subscription> [modelId]")
        return "\n".join(lines)

    if len(args) < 2:
        return (
            "用法: /model <agent> <subscription> [modelId]\n"
            "示例: /model planner coding\n示例: /model builder coding qwen2.5:7b"
        )

    agent_id, sub_key = args[0], args[1]
    model_id = args[2] if len(args) > 2 else None

    if agent_id not in agent_ids:
        return f"未知 Agent: {agent_id}\n可用: {', '.join(agent_ids)}"
    if sub_key not in sub_keys:
        return f"未知订阅: {sub_key}\n可用: {', '.join(sub_keys)}"

    override: Dict[str, Optional[str]] = {"subscription": sub_key}
    if model_id:
        override["modelId"] = model_id
    set_runtime_override(agent_id, override)

    sub_info = config.llm.subscriptions.get(sub_key)
    lines = [f"✓ {agent_id} 已切换:"]
    lines.append(f"  subscription: {sub_key} ({sub_info.provider if sub_info else '未知'})")
    if override.get("modelId"):
        lines.append(f"  model: {override['modelId']}")
    return "\n".join(lines)


# ── /session ──────────────────────────────────────────────


def handle_session_command(
    args: List[str],
    session_id: Optional[str] = None,
    current_state: Optional[Dict[str, Any]] = None,
) -> str:
    from ..runtime.budget import estimate_messages_tokens

    db_path = resolve_session_db_path()
    session_manager = SessionManager(db_path)
    try:
        sub = args[0] if args else ""

        if sub == "status":
            if session_id is None or current_state is None:
                return "当前没有活跃的会话"
            messages = current_state.get("messages", [])
            token_count = estimate_messages_tokens(messages)
            lines = [
                f"会话 ID: {session_id}",
                f"消息数: {len(messages)}",
                f"步骤数: {current_state.get('stepCount', 0)}",
                f"估算 Token: {token_count}",
                f"上下文窗口: {get_config().context.contextWindow}",
                f"Token 占比: {token_count / get_config().context.contextWindow * 100:.1f}%",
            ]
            todo_list = current_state.get("todoList") or []
            if todo_list:
                done = sum(1 for t in todo_list if t.get("done"))
                lines.append(f"TODO: {done}/{len(todo_list)} 已完成")
            return "\n".join(lines)

        if sub == "summary":
            if session_id is None:
                return "当前没有活跃的会话"
            summary = session_manager.get_session_summary(session_id)
            if summary is None:
                return "当前会话暂无摘要（Token 使用未达到阈值，尚未触发自动摘要）"
            return f"当前会话摘要:\n{summary}"

        if sub == "todo":
            todo_list = (current_state or {}).get("todoList") or []
            if not todo_list:
                return "当前没有 TODO 任务"
            lines = [f"- [{'x' if t.get('done') else ' '}] {t.get('text')}" for t in todo_list]
            return "当前 TODO 列表:\n" + "\n".join(lines)

        if sub == "list":
            sessions = session_manager.list_sessions()
            if not sessions:
                return "暂无历史会话"
            lines = [f"历史会话 ({len(sessions)}):"]
            for s in sessions:
                lines.append(f"  {s['id']}  消息: {s['messageCount']}  步骤: {s['stepCount']}")
            return "\n".join(lines)

        return "\n".join([
            "/session 子命令:",
            "  status  — 显示当前会话 Token 用量、消息数、TODO 状态",
            "  summary — 显示当前摘要内容",
            "  todo    — 显示当前 TODO 列表",
            "  list    — 列出所有历史会话",
            "用法: /session <子命令>",
        ])
    finally:
        session_manager.close()


# ── 清理 / 初始化（共享） ─────────────────────────────────


async def cleanup() -> None:
    from ..tools.mcp_client import mcp_lifecycle

    try:
        await asyncio.wait_for(mcp_lifecycle.shutdown(), timeout=2)
    except Exception:
        pass


async def initialize_mcp() -> str:
    from ..tools.mcp_client import mcp_lifecycle

    servers = get_config().mcp.servers
    if not servers:
        return "[MCP] 未配置 MCP 服务器，跳过初始化"
    try:
        await mcp_lifecycle.start(list(servers))
        return f"[MCP] 初始化完成（{len(servers)} 个服务器）"
    except Exception as err:
        return (
            f"[MCP] 初始化失败: {err}\n"
            "[MCP] 提示: 请检查 config/mcp.jsonc 中的服务器地址是否正确、服务器是否已启动"
        )
