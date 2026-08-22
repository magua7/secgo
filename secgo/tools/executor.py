"""工具执行器：统一入口，含权限检查、MCP 路由与技能工具。"""

import asyncio
import json
import os
from typing import Any, Dict, List, Optional

from ..config.config import get_config
from ..kernel.skill_loader import list_skills, read_skill
from ..runtime.workspace import (
    _truncate_output_text,
    execute_script as ws_execute_script,
    get_session_tmpdir,
    get_shell,
    get_workspace_base,
    write_file as ws_write_file,
)
from .local_script_loader import execute_script_tool, get_script_tool_names
from .local_web_search import execute_web_search
from .mcp_client import mcp_client
from .registry import all_tool_definitions

EXECUTE_TIMEOUT_S = 10

ToolResult = Dict[str, Any]


def _write_evidence(session_id: str, tool_name: str, result: ToolResult) -> None:
    """工具结果证据落盘：workspace/<session_id>/evidence/<时间戳>_<tool_name>.txt。

    仅用于审计复盘，不进入消息上下文；写盘失败不影响工具返回。
    """
    try:
        from datetime import datetime

        evidence_dir = get_workspace_base() / session_id / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        safe_name = tool_name.replace("/", "_").replace("\\", "_")
        lines = [f"# tool={tool_name} success={result.get('success')} @ {ts}"]
        if result.get("output"):
            lines.append("--- output ---")
            lines.append(str(result["output"]))
        if result.get("error"):
            lines.append("--- error ---")
            lines.append(str(result["error"]))
        path = evidence_dir / f"{ts}_{safe_name}.txt"
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))
            f.write("\n")
    except Exception:
        pass


def check_permission(tool_name: str, agent_id: str) -> bool:
    # MCP 工具：允许所有 Agent
    if tool_name.startswith("mcp_"):
        return True
    tool_def = next((d for d in all_tool_definitions() if d.name == tool_name), None)
    if tool_def is None:
        # 未知工具（如 task_complete 等内置工具）放行
        return True
    if len(tool_def.allowed_agents) == 0:
        return True
    return agent_id in tool_def.allowed_agents


async def execute_tool(
    tool_name: str,
    args: Dict[str, Any],
    session_id: str = "default",
    agent_id: Optional[str] = None,
) -> ToolResult:
    # 鉴权：如果提供了 agentId，先检查权限
    if agent_id is not None and not check_permission(tool_name, agent_id):
        return {
            "success": False,
            "error": f'Permission denied: agent "{agent_id}" is not allowed to use tool "{tool_name}"',
        }

    result = await _dispatch_tool(tool_name, args, session_id, agent_id)
    # 工具结果证据落盘（仅审计复盘，写盘失败不影响返回）
    _write_evidence(session_id, tool_name, result)
    return result


async def _dispatch_tool(
    tool_name: str,
    args: Dict[str, Any],
    session_id: str = "default",
    agent_id: Optional[str] = None,
) -> ToolResult:
    if tool_name.startswith("mcp_"):
        return await mcp_client.call_tool(tool_name, args)

    if tool_name == "execute_bash":
        return await _execute_bash(args.get("command") or "", session_id)
    if tool_name == "write_to_workspace":
        return _write_to_workspace(
            session_id, args.get("filename") or "", args.get("content") or ""
        )
    if tool_name == "execute_workspace_script":
        return await ws_execute_script(
            session_id, args.get("filename") or "", list(args.get("args") or [])
        )
    if tool_name == "web_search":
        return await execute_web_search(args.get("query") or "")
    if tool_name == "task_complete":
        return {"success": True, "output": f"任务已完成。摘要: {args.get('summary', '')}"}
    if tool_name == "skill_list":
        return _skill_list()
    if tool_name == "skill_read":
        return _skill_read(args.get("name") or "")

    # 脚本工具（.py/.php 动态加载）
    if tool_name in get_script_tool_names():
        return await execute_script_tool(tool_name, args)

    return {"success": False, "error": f"Unknown tool: {tool_name}"}


async def _execute_bash(command: str, session_id: str = "default") -> ToolResult:
    if not command or not command.strip():
        return {"success": False, "error": "Empty command"}

    security = get_config().security
    trimmed = command.strip()
    cmd_name = trimmed.split(None, 1)[0] if trimmed.split() else ""

    for pattern in security.blockedCommands:
        if pattern and pattern in trimmed:
            return {
                "success": False,
                "error": (
                    f'Command rejected: "{trimmed}" matched blocked pattern "{pattern}". '
                    f'Fix: remove or replace the dangerous subcommand "{pattern}" with a safe alternative.'
                ),
            }

    if security.allowedCommands and cmd_name not in security.allowedCommands:
        return {
            "success": False,
            "error": (
                f'Command blocked: "{cmd_name}" is not in the allowed commands list. '
                f"Allowed: {', '.join(security.allowedCommands)}"
            ),
            "output": (
                f'Command blocked: "{cmd_name}" is not in the allowed commands list. '
                f"Allowed: {', '.join(security.allowedCommands)}"
            ),
        }

    try:
        shell, flag = get_shell()
        # 注入会话级临时目录：$TMPDIR/$TMP/$TEMP 指向 workspace/<session_id>/.tmp，
        # 使 Agent 的 cat > /tmp/xx 落到受控工作区而非系统临时目录
        env = None
        if session_id:
            tmp_dir = str(get_session_tmpdir(session_id))
            env = os.environ.copy()
            env["TMPDIR"] = tmp_dir
            env["TMP"] = tmp_dir
            env["TEMP"] = tmp_dir
        proc = await asyncio.create_subprocess_exec(
            shell, flag, command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=EXECUTE_TIMEOUT_S)
        except asyncio.TimeoutError:
            proc.kill()
            return {
                "success": False,
                "error": (
                    f"Command timed out after {EXECUTE_TIMEOUT_S}s. Command: {command}\n"
                    "提示：长时间运行的临时脚本请先写入工作区（用 write_to_workspace 或 execute_workspace_script），再分步执行。"
                ),
            }
        out_text = stdout.decode("utf-8", errors="replace")
        err_text = stderr.decode("utf-8", errors="replace")
        output_text = _truncate_output_text(out_text)
        if proc.returncode != 0:
            return {
                "success": False,
                "output": output_text,
                "error": (
                    f"Command exited with code {proc.returncode}.\n"
                    f"stderr: {err_text}\nstdout: {out_text}"
                ),
            }
        return {"success": True, "output": output_text or "(no output)"}
    except OSError as err:
        return {"success": False, "error": f"Failed to execute command: {err}"}


def _write_to_workspace(session_id: str, filename: str, content: str) -> ToolResult:
    result = ws_write_file(session_id, filename, content)
    if not result["safe"]:
        return {"success": False, "error": result.get("error")}
    return {
        "success": True,
        "output": (
            f'File "{filename}" written successfully to workspace ({len(content.encode("utf-8"))} bytes).'
        ),
    }


def _skill_list() -> ToolResult:
    skills = list_skills()
    if not skills:
        return {"success": True, "output": "技能库为空（检查 skill/ 目录与 SECGO_SKILLS_DIR 环境变量）。"}
    lines = [f"SEC-GO 安全技能库（启用 {len(skills)} 个）:"]
    for s in skills:
        lines.append(f"- {s['name']} [{s['group']}]: {s['description']}")
    return {"success": True, "output": "\n".join(lines)}


def _skill_read(name: str) -> ToolResult:
    if not name:
        return {"success": False, "error": "skill_read 需要 name 参数（可用 skill_list 查询技能名）"}
    text = read_skill(name)
    if text is None:
        return {"success": False, "error": f"技能不存在: {name}（可用 skill_list 查询）"}
    return {"success": True, "output": text}
