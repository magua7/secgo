"""CLI 交互式 TUI：rich 渲染 + prompt_toolkit 输入，事件流实时展示。"""

import asyncio
import sys
from typing import Any, Dict, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from .config.config import get_config
from .kernel.commands import (
    cleanup,
    handle_mcp_command,
    handle_model_command,
    handle_session_command,
    handle_skill_command,
    initialize_mcp,
)
from .kernel.handoff_engine import provide_user_input, run_engine
from .runtime.eventbus import event_bus

console: Optional[Console] = None

PROMPT_STYLE = Style.from_dict({
    "prompt": "bold #00ff87",
})

AGENT_COLORS = {
    "planner": "#00d7ff",
    "research": "#00ff87",
    "builder": "#ffd700",
    "operator": "#ff5fd7",
    "system": "#888888",
}

_LOGO_ART = r"""
  ██████  ███████  ██████        ██████   ██████
 ██       ██      ██      ▄▄▄▄▄  ██    ██ ██    ██
  █████   █████   ██       ██    ██    ██ ██    ██
      ██  ██      ██       ██    ██    ██ ██    ██
 ██████   ███████  ██████   ██   ██████   ██████
"""

_AGENT_LABELS = {
    "planner": "任务规划",
    "research": "信息检索",
    "builder": "代码构建",
    "operator": "系统执行",
}


def print_logo() -> None:
    text = Text()
    text.append(_LOGO_ART, style="bold cyan")
    text.append("Multi-Agent Security Engine  |  100+ 安全技能库  |  MCP 扩展\n", style="#888888")
    text.append("命令: /skill /mcp /model /session /clear /exit", style="#666666")
    console.print(Panel(text, border_style="cyan"))


def _agent_color(agent_id: str) -> str:
    return AGENT_COLORS.get(agent_id, "#ffffff")


def bind_events() -> None:
    def on_engine_start(data: Dict[str, Any]) -> None:
        console.print()
        console.print(f"▶ 任务: {data.get('user_input', '')}", style="bold white")

    def on_agent_thinking(data: Dict[str, Any]) -> None:
        agent_id = data.get("agent_id", "?")
        label = _AGENT_LABELS.get(agent_id, agent_id)
        console.print(f"\n[{_agent_color(agent_id)}]● {agent_id} ({label}) 思考中...[/]", style=_agent_color(agent_id))

    def on_agent_switch(data: Dict[str, Any]) -> None:
        console.print(
            f"⟳ 交接: {data.get('from_agent_id')} → {data.get('to_agent_id')}"
            f"（{data.get('reason', '')}）",
            style="bold yellow",
        )

    def on_tool_start(data: Dict[str, Any]) -> None:
        args = data.get("args") or {}
        args_str = str(args)
        if len(args_str) > 120:
            args_str = args_str[:120] + "..."
        console.print(f"  🔧 [bold yellow]{data.get('tool_name')}[/] {args_str}", style="yellow")

    def on_tool_end(data: Dict[str, Any]) -> None:
        result = data.get("result")
        result_str = str(result) if isinstance(result, str) else str(result)
        if len(result_str) > 300:
            result_str = result_str[:300] + "..."
        console.print(f"     ↳ {result_str}", style="dim")

    def on_llm_stream(data: Dict[str, Any]) -> None:
        chunk = data.get("chunk", "")
        console.print(chunk, end="", markup=False, highlight=False)

    def on_engine_text(data: Dict[str, Any]) -> None:
        console.print()

    def on_todo_updated(data: Dict[str, Any]) -> None:
        todo_list = data.get("todo_list") or []
        if not todo_list:
            return
        console.print("  [TODO]", style="bold cyan")
        for todo in todo_list:
            mark = "x" if todo.get("done") else " "
            console.print(f"    - [{mark}] {todo.get('text')}", style="dim")

    def on_engine_error(data: Dict[str, Any]) -> None:
        console.print(f"[red]✗ 引擎错误: {data.get('error', '')}[/red]")

    def on_engine_end(data: Dict[str, Any]) -> None:
        reason = data.get("reason", "")
        total_steps = data.get("total_steps", 0)
        console.print(
            f"\n■ 结束 | {reason} | {total_steps} 步\n", style="bold green"
        )

    def on_budget_exceeded(data: Dict[str, Any]) -> None:
        console.print(
            f"[red]⚠ 预算超限: {data.get('usage', 0)}/{data.get('limit', 0)} tokens[/red]"
        )

    event_bus.on("engine:start", on_engine_start)
    event_bus.on("agent:thinking", on_agent_thinking)
    event_bus.on("agent:switch", on_agent_switch)
    event_bus.on("tool:stream-start", on_tool_start)
    event_bus.on("tool:stream-end", on_tool_end)
    event_bus.on("llm:stream", on_llm_stream)
    event_bus.on("engine:text", on_engine_text)
    event_bus.on("todo:updated", on_todo_updated)
    event_bus.on("engine:error", on_engine_error)
    event_bus.on("engine:end", on_engine_end)
    event_bus.on("budget:exceeded", on_budget_exceeded)


async def _handle_slash_command(text: str) -> Optional[bool]:
    """处理 / 命令。返回 True 表示退出程序。"""
    parts = text[1:].split()
    cmd = parts[0].lower() if parts else ""
    args = parts[1:]

    if cmd == "clear":
        console.clear()
        print_logo()
    elif cmd == "exit":
        await cleanup()
        return True
    elif cmd == "skill":
        console.print(handle_skill_command(args), markup=False)
    elif cmd == "mcp":
        console.print(await handle_mcp_command(args[0] if args else None), markup=False)
    elif cmd == "model":
        console.print(handle_model_command(args), markup=False)
    elif cmd == "session":
        console.print(handle_session_command(args), markup=False)
    elif cmd == "help":
        console.print(
            "/skill list | /skill <name> | /skill search <kw> | /mcp status | "
            "/model | /session list | /clear | /exit",
            markup=False,
        )
    else:
        console.print(
            f"未知命令: /{cmd}。可用命令: /skill, /mcp, /model, /session, /clear, /exit",
            style="red",
        )
    return None


async def run_tui() -> None:
    from .config.wizard import run_first_run_wizard

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("SEC-GO CLI 需要在真实终端中运行（请双击 cli.bat）。")
        print("非交互场景请使用: python -m secgo.headless \"任务描述\"")
        return

    await run_first_run_wizard()

    mcp_msg = await initialize_mcp()
    console.print(mcp_msg, style="dim")

    bind_events()
    print_logo()

    session = PromptSession()
    awaiting = asyncio.Event()
    awaiting_session_id: Optional[str] = None

    def on_awaiting_input(data: Dict[str, Any]) -> None:
        nonlocal awaiting_session_id
        awaiting_session_id = data.get("session_id")
        awaiting.set()

    event_bus.on("engine:awaiting_input", on_awaiting_input)

    try:
        while True:
            try:
                text = await session.prompt_async(
                    [("class:prompt", "> ")],
                    style=PROMPT_STYLE,
                    enable_history_search=True,
                )
            except (KeyboardInterrupt, EOFError):
                console.print()
                await cleanup()
                return

            text = text.strip()
            if not text:
                continue

            if text.startswith("/"):
                should_exit = await _handle_slash_command(text)
                if should_exit:
                    return
                continue

            engine_task = asyncio.create_task(run_engine(text))
            try:
                while not engine_task.done():
                    if awaiting.is_set():
                        awaiting.clear()
                        console.print("  ⏸ 引擎等待输入…", style="yellow")
                        try:
                            follow_up = await session.prompt_async(
                                [("class:prompt", "> ")],
                                style=PROMPT_STYLE,
                            )
                        except (KeyboardInterrupt, EOFError):
                            if awaiting_session_id:
                                provide_user_input(awaiting_session_id, "[用户已中断等待，请输出当前阶段总结]")
                            continue
                        if awaiting_session_id:
                            provide_user_input(awaiting_session_id, follow_up)
                    else:
                        await asyncio.wait({engine_task}, timeout=0.1)
                await engine_task
            except asyncio.CancelledError:
                engine_task.cancel()
                raise
            except KeyboardInterrupt:
                console.print("\n[已中断]", style="yellow")
                engine_task.cancel()
                await asyncio.gather(engine_task, return_exceptions=True)
                continue
            except Exception as err:
                console.print(f"[red]✗ 引擎异常: {err}[/red]")
    finally:
        event_bus.off("engine:awaiting_input", on_awaiting_input)
        await cleanup()


def main() -> None:
    global console
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    console = Console()
    try:
        asyncio.run(run_tui())
    except KeyboardInterrupt:
        pass
