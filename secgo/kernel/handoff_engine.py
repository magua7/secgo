"""SEC-GO 多 Agent 交接引擎(纯函数引擎 + 事件总线输出 + 用户输入挂起机制)."""

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Set

from ..config.config import get_config
from ..model.provider import stream_agent_response
from ..runtime.budget import BudgetManager, estimate_messages_tokens, estimate_tokens
from ..runtime.eventbus import event_bus, set_current_session
from ..runtime.session import SessionManager, resolve_session_db_path
from ..runtime.snapshot import classify_tool_evidence
from ..tools.executor import execute_tool
from ..tools.mcp_client import mcp_client
from .plan_state import PlanState, ReplanDetector, DecisionRecord
from ..tools.registry import (
    all_tool_definitions,
    build_tool_set,
    get_tools_for_agent,
)
from .agents import get_agent, model_supports_native_tools
from .pipeline import (
    TodoTracker,
    compact_messages_with_summary,
    compact_old_tool_results,
    compact_tool_output,
    format_tool_results,
    inject_tools_to_prompt,
    normalize_tool_calls,
    parse_tool_calls_from_text,
    should_summarize,
    summarize_messages,
)

logger = logging.getLogger("secgo.session")


def _save_state_with_retry(manager: SessionManager, session_id: str, state: Dict[str, Any], attempts: int = 3) -> bool:
    """关键执行状态落库:失败必须可见(log + 重试 + persistence:warning),绝不静默吞掉."""
    last: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            manager.save_state(session_id, state)
            return True
        except Exception as exc:  # 不 pass:记录并重试
            last = exc
            logger.exception(
                "session persistence failure (attempt %d) for %s", attempt + 1, session_id
            )
            if attempt < attempts - 1:
                time.sleep(0.05 * (attempt + 1))
    try:
        event_bus.emit("persistence:warning", {
            "session_id": session_id,
            "error": (str(last)[:300] if last else "unknown persistence error"),
        })
    except Exception:
        logger.exception("failed to emit persistence:warning")
    return False


def _sanitize_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """清洗消息历史:移除/转换孤立的 tool 消息(OpenAI 兼容约束)."""
    if not messages:
        return messages

    result: List[Dict[str, Any]] = []
    last_assistant_tool_ids: Set[str] = set()

    for msg in messages:
        role = msg.get("role")
        if role == "assistant":
            ids: Set[str] = set()
            for tc in msg.get("tool_calls") or []:
                if isinstance(tc, dict) and tc.get("id"):
                    ids.add(tc["id"])
            last_assistant_tool_ids = ids
            result.append(msg)
        elif role == "tool":
            tool_call_id = msg.get("tool_call_id", "")
            all_match = bool(tool_call_id) and tool_call_id in last_assistant_tool_ids
            if all_match:
                result.append(msg)
            else:
                # 孤立 tool 消息 → 转为 user 消息,保留上下文信息
                result.append({
                    "role": "user",
                    "content": f"[工具结果 {tool_call_id}]: {msg.get('content', '')}",
                })
        else:
            last_assistant_tool_ids = set()
            result.append(msg)

    return result


# ── 用户输入等待机制 ──────────────────────────────────────

CONTROL_TOOLS = {"handoff_to_agent", "task_complete"}

REPLAN_SYSTEM_PROMPT = """[系统 RePlan 指令]

系统检测到当前执行路径需要重新规划.触发原因: {trigger}.

请按以下步骤执行:
1. 回顾当前任务目标和已有发现
2. 评估当前策略的有效性
3. 制定新的执行计划(包含具体步骤和预期目标)
4. 如果方向彻底改变,handoff 给 Planner 重新规划

原计划(将被替换): {current_plan}
新计划请以 '## 新计划' 开头输出."""

AGENT_PROTOCOL_ERROR = """[Agent Protocol Error]

A single Agent turn may contain either:
1. one or more business tools; or
2. exactly one control action.

Do not mix business tools with handoff_to_agent or task_complete.
Choose one action type and re-evaluate the task state."""

_input_resolvers: Dict[str, asyncio.Future] = {}


async def _wait_for_user_input(session_id: str) -> str:
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    previous = _input_resolvers.get(session_id)
    if previous is not None and not previous.done():
        previous.cancel()
    _input_resolvers[session_id] = future
    try:
        return await future
    finally:
        if _input_resolvers.get(session_id) is future:
            _input_resolvers.pop(session_id, None)


def provide_user_input(session_id: str, user_input: str) -> bool:
    """向引擎提供新的用户输入,恢复被挂起的引擎循环."""
    future = _input_resolvers.get(session_id)
    if future is None or future.done():
        return False
    future.set_result(user_input)
    return True


def is_engine_awaiting_input(session_id: str) -> bool:
    future = _input_resolvers.get(session_id)
    return future is not None and not future.done()


def cancel_waiting_input(session_id: str) -> bool:
    future = _input_resolvers.get(session_id)
    if future is None or future.done():
        _input_resolvers.pop(session_id, None)
        return False
    future.cancel()
    _input_resolvers.pop(session_id, None)
    return True


def _mcp_tools_for_agent(agent_id: str, context: str) -> List[Dict[str, Any]]:
    """Operator 全量、其余 Agent 按关键词评分取前 5(移植 TS router 逻辑)."""
    all_tools = mcp_client.get_tools()
    if not all_tools:
        return []

    if agent_id == "operator":
        return [
            {"name": t["name"], "description": f"[MCP] {t['description']}",
             "input_schema": t["input_schema"]}
            for t in all_tools
        ]

    keywords = {
        "operator": ["execute", "run", "scan", "nmap", "system", "process", "network",
                     "bash", "shell", "install", "deploy", "service"],
        "research": ["fetch", "search", "browse", "web", "crawl", "read", "url", "http",
                     "query", "scrape", "extract"],
        "builder": ["file", "write", "code", "compile", "build", "edit", "create",
                    "template", "generate", "parse"],
        "planner": ["list", "info", "status", "check", "overview", "summary", "plan", "analyze"],
    }.get(agent_id, [])

    context_lower = context.lower()
    scored: List[tuple] = []
    for tool in all_tools:
        name_lower = tool["name"].lower()
        desc_lower = tool["description"].lower()
        score = 0
        for kw in keywords:
            if kw in name_lower or kw in desc_lower:
                score += 1
        for word in context_lower.split():
            if len(word) > 2 and (word in name_lower or word in desc_lower):
                score += 2
        scored.append((tool, score))

    scored.sort(key=lambda item: item[1], reverse=True)
    return [
        {"name": t["name"], "description": f"[MCP] {t['description']}",
         "input_schema": t["input_schema"]}
        for t, _score in scored[:5]
    ]


# ── 引擎主循环 ────────────────────────────────────────────


async def run_engine(user_input: str, session_id: Optional[str] = None) -> Dict[str, Any]:
    sid = session_id or str(uuid.uuid4())
    set_current_session(sid)

    budget_manager = BudgetManager(get_config().budget.maxTokensPerSession)

    db_path = resolve_session_db_path()
    session_manager = SessionManager(db_path)

    active_agent_id = "planner"
    messages: List[Dict[str, Any]] = [{"role": "user", "content": user_input}]
    # 步骤计数拆分为两层：
    # - run_step_count：本次 run_engine 执行窗口已用步数，用于限制 maxStepsPerTask（每次 Run 从 0 开始）
    # - total_step_count：整个 Session 累计步数，用于审计 / Timeline / 无进展检测（持久化为 stepCount）
    run_step_count = 0
    total_step_count = 0
    max_replans = get_config().budget.maxReplansPerRun
    todo_tracker = TodoTracker()

    saved_state = session_manager.load_state(sid)
    plan_state = PlanState(goal=user_input[:500])
    # 从保存的状态恢复 PlanState
    if saved_state is not None:
        plan_data = saved_state.get("planState")
        if plan_data:
            plan_state = PlanState.from_serializable(plan_data)

    saved_state = session_manager.load_state(sid)
    if saved_state is not None:
        active_agent_id = saved_state.get("activeAgentId", "planner")
        messages = list(saved_state.get("messages") or [])
        total_step_count = int(saved_state.get("stepCount", 0))
        todo_list = saved_state.get("todoList")
        if todo_list:
            todo_tracker.restore(list(todo_list))

    # 状态保存合并:同一步内的多次保存只保留最新状态,落库推迟到步骤边界/退出前
    # (事件循环内每步至多序列化一次;最后一步的保存由 finally 兜底落库,不丢失)
    pending_save: Optional[Dict[str, Any]] = None

    def save_session_state(state: Dict[str, Any]) -> None:
        nonlocal pending_save
        pending_save = state

    def flush_pending_save() -> None:
        nonlocal pending_save
        state = pending_save
        pending_save = None
        if state is None:
            # 无待保存状态(如引擎异常崩溃)时也构造一份,保证 engine context 兜底落库
            state = {
                "activeAgentId": active_agent_id,
                "messages": messages,
                "stepCount": total_step_count,
                "todoList": todo_tracker.get_all_tasks(),
                "planState": plan_state.to_serializable(),
            }
        _save_state_with_retry(session_manager, sid, state)

    # 修正:engine:start 必须携带解析后的 sid(原实现传的是可能为 None 的入参 session_id)
    event_bus.emit("engine:start", {"session_id": sid, "user_input": user_input})

    try:
        while run_step_count < get_config().budget.maxStepsPerTask:
            flush_pending_save()  # 上一步的最终状态在进入下一步前落库
            try:
                agent = get_agent(active_agent_id)
            except ValueError:
                agent = get_agent("planner")
                active_agent_id = "planner"
            run_step_count += 1
            total_step_count += 1

            # ── RePlan 检测 ──────────────────────────────────────
            replan_trigger = plan_state.detector.check(total_step_count, active_agent_id)
            if (
                replan_trigger is not None
                and plan_state.replan_count >= max_replans
                and not plan_state.exhaustion_notice_injected
            ):
                # 达到最大重规划次数 → 明确 fallback：不再 RePlan，注入收尾指引（一次性）
                plan_state.exhaustion_notice_injected = True
                event_bus.emit("decision:reason", {
                    "session_id": sid,
                    "decision": {
                        "id": f"decision-exhausted-{uuid.uuid4().hex[:8]}",
                        "timestamp": time.time(),
                        "trigger": "replan_exhausted",
                        "trigger_detail": f"已达到最大重规划次数 {max_replans}",
                        "observation": plan_state.current_plan[:500],
                        "candidates": [],
                        "selected": "",
                        "reason": "重规划次数已达上限，改为基于现有发现总结收尾",
                        "rejected": [],
                    },
                    "step": total_step_count,
                })
                plan_state.detector.reset_after_replan()
                messages.append({
                    "role": "user",
                    "content": (
                        "[系统提示] 已达最大重规划次数。请基于已有发现总结当前进展；"
                        "若是子 Agent，请 handoff 给 Planner，由 Planner 决定继续或收尾。"
                    ),
                })
            elif replan_trigger is not None and plan_state.replan_count < max_replans:
                # 触发生成决策（trigger_replan 内部会重置本轮触发器状态）
                # 注：达到 max_replans 后（无论提示是否注入过）一律不再 RePlan，静默吞掉触发条件
                old_plan = plan_state.current_plan
                decision = plan_state.trigger_replan(
                    trigger=replan_trigger["trigger"],
                    trigger_detail=replan_trigger["detail"],
                    active_agent_id=active_agent_id,
                )
                event_bus.emit("decision:reason", {
                    "session_id": sid,
                    "decision": decision.to_dict(),
                    "step": total_step_count,
                })
                replan_prompt = REPLAN_SYSTEM_PROMPT.format(
                    trigger=replan_trigger["detail"],
                    current_plan=old_plan[:200],  # 原计划（触发前），绝不把新计划误标为「原计划」
                )
                messages.append({
                    "role": "user",
                    "content": replan_prompt,
                })
                # 如果选中的策略目标是 handoff 回 Planner，强制 handoff
                selected_target = next(
                    (c.target_agent for c in decision.candidates if c.id == decision.selected), None
                )
                if selected_target == "planner" and active_agent_id != "planner":
                    prev_agent_id = active_agent_id
                    active_agent_id = "planner"
                    event_bus.emit("agent:switch", {
                        "session_id": sid,
                        "from_agent_id": prev_agent_id,
                        "to_agent_id": active_agent_id,
                        "reason": f"RePlan: {replan_trigger['trigger']} - {decision.reason[:100]}",
                    })
                    messages.append({
                        "role": "user",
                        "content": f"[RePlan 强制 Handoff from {prev_agent_id}]: {decision.reason}",
                    })
                    continue
            # ── 每 10 步通用提示(仅当未触发 RePlan 时) ──
            elif run_step_count % 10 == 0 and run_step_count > 0:
                messages.append({
                    "role": "user",
                    "content": (
                        f"[系统提示:你已执行 {total_step_count} 步.如果长时间无进展,"
                        "考虑总结当前发现并 handoff 给 Planner.]"
                    ),
                })

            budget_check = budget_manager.check_budget(sid)
            if not budget_check["allowed"]:
                event_bus.emit("budget:exceeded", {
                    "session_id": sid,
                    "usage": budget_check["usage"],
                    "limit": get_config().budget.maxTokensPerSession,
                })
                event_bus.emit("engine:end", {
                    "session_id": sid,
                    "reason": "budget_exceeded",
                    "total_steps": total_step_count,
                })
                save_session_state({
                    "activeAgentId": active_agent_id,
                    "messages": messages,
                    "stepCount": total_step_count,
                    "todoList": todo_tracker.get_all_tasks(),
                "planState": plan_state.to_serializable(),
                })
                return {"reason": "budget_exceeded", "total_steps": total_step_count}

            event_bus.emit("agent:thinking", {"session_id": sid, "agent_id": agent.id})

            # 本地工具 + MCP 工具
            tool_defs = get_tools_for_agent(agent.id)
            tools = build_tool_set(tool_defs)
            if mcp_client.is_connected():
                try:
                    # 评分上下文:从最近消息向前累计,总字符数约 50KB 即停止(内部评分输入,可近似)
                    context_parts: List[str] = []
                    context_budget = 50 * 1024
                    for m in reversed(messages):
                        if context_budget <= 0:
                            break
                        content = m.get("content", "") if isinstance(m.get("content"), str) else ""
                        if not content:
                            continue
                        context_parts.append(content)
                        context_budget -= len(content)
                    context = " ".join(reversed(context_parts))
                    tools = tools + _mcp_tools_for_agent(agent.id, context)
                except Exception:
                    pass

            subscription = get_config().llm.subscriptions.get(agent.subscription)
            supports_tools = subscription is not None and model_supports_native_tools(
                agent.model_id
            )
            effective_tools = tools if supports_tools else []

            enhanced_system_prompt: Optional[str] = None
            if not supports_tools and tools:
                agent_tool_defs = [
                    d for d in all_tool_definitions()
                    if len(d.allowed_agents) == 0 or agent.id in d.allowed_agents
                ]
                if agent_tool_defs:
                    enhanced_system_prompt = inject_tools_to_prompt(
                        [
                            {"name": d.name, "description": d.description}
                            for d in agent_tool_defs
                        ],
                        agent.system_prompt,
                    )

            try:
                safe_messages = _sanitize_messages(messages)
                safe_messages = compact_old_tool_results(safe_messages)

                if run_step_count % 5 == 0 and should_summarize(safe_messages):
                    original_tokens = estimate_messages_tokens(safe_messages)
                    summary = await summarize_messages(safe_messages, agent.subscription)
                    compacted = await compact_messages_with_summary(safe_messages, summary)
                    if len(compacted) < len(safe_messages):
                        # 原地压缩写回消息本体:后续 append/保存/上下文构建基于压缩后的历史;
                        # compact_messages_with_summary 已保证首条 user 消息保留(head 规则)
                        messages[:] = compacted
                    safe_messages = compacted
                    summary_tokens = estimate_messages_tokens(safe_messages)
                    event_bus.emit("context:summarized", {
                        "session_id": sid,
                        "original_tokens": original_tokens,
                        "summary_tokens": summary_tokens,
                    })
                    save_session_state({
                        "activeAgentId": active_agent_id,
                        "messages": messages,
                        "stepCount": total_step_count,
                        "summaryCache": summary,
                        "todoList": todo_tracker.get_all_tasks(),
                "planState": plan_state.to_serializable(),
                    })

                formatted_todo = todo_tracker.get_formatted_todo()
                if formatted_todo:
                    safe_messages.append({"role": "user", "content": formatted_todo})

                response = await stream_agent_response(
                    agent, safe_messages, effective_tools, enhanced_system_prompt
                )
            except Exception as err:
                error_message = str(err)
                event_bus.emit("engine:error", {
                    "session_id": sid,
                    "agent_id": agent.id,
                    "error": error_message,
                })
                event_bus.emit("engine:end", {
                    "session_id": sid,
                    "reason": "error",
                    "total_steps": total_step_count,
                })
                save_session_state({
                    "activeAgentId": active_agent_id,
                    "messages": messages,
                    "stepCount": total_step_count,
                    "todoList": todo_tracker.get_all_tasks(),
                "planState": plan_state.to_serializable(),
                })
                return {"reason": "error", "total_steps": total_step_count}

            if response.text:
                budget_manager.add_usage(sid, estimate_tokens(response.text))

            messages.extend(response.response_messages)

            if response.text:
                new_todos = todo_tracker.extract_todo_from_text(response.text)
                if new_todos:
                    todo_tracker.update_todo(new_todos)
                    event_bus.emit("todo:updated", {
                        "session_id": sid,
                        "todo_list": new_todos,
                    })
                    # Planner 的真实执行计划同步进 PlanState，使 RePlan 的「原计划」真实可用
                    formatted_plan = todo_tracker.get_formatted_todo()
                    if formatted_plan:
                        plan_state.set_plan(formatted_plan)

            fallback_calls = []
            if not supports_tools and response.text:
                fallback_calls = parse_tool_calls_from_text(response.text)

            raw_calls = [
                {
                    "toolCallId": tc.get("tool_call_id") or tc.get("id"),
                    "toolName": tc.get("tool_name") or tc.get("name"),
                    "input": tc.get("input") or tc.get("arguments") or {},
                }
                for tc in list(response.tool_calls) + list(fallback_calls)
            ]
            normalized_calls = normalize_tool_calls(raw_calls)

            save_session_state({
                "activeAgentId": active_agent_id,
                "messages": messages,
                "stepCount": total_step_count,
                "todoList": todo_tracker.get_all_tasks(),
                "planState": plan_state.to_serializable(),
            })

            if response.text:
                event_bus.emit("engine:text", {
                    "session_id": sid,
                    "agent_id": agent.id,
                    "text": response.text,
                })

            control_calls = [tc for tc in normalized_calls if tc["name"] in CONTROL_TOOLS]
            business_calls = [tc for tc in normalized_calls if tc["name"] not in CONTROL_TOOLS]

            if len(control_calls) > 1 or (control_calls and business_calls):
                if supports_tools:
                    for tc in normalized_calls:
                        messages.append(format_tool_results(
                            tc["id"], tc["name"],
                            {"success": False, "error": AGENT_PROTOCOL_ERROR},
                        ))
                messages.append({"role": "user", "content": AGENT_PROTOCOL_ERROR})
                save_session_state({
                    "activeAgentId": active_agent_id,
                    "messages": messages,
                    "stepCount": total_step_count,
                    "todoList": todo_tracker.get_all_tasks(),
                "planState": plan_state.to_serializable(),
                })
                continue

            control_call = control_calls[0] if control_calls else None
            if control_call is not None and control_call["name"] == "task_complete":
                if active_agent_id != "planner":
                    error_msg = (
                        f'[Agent Permission Error] Agent "{active_agent_id}" cannot call '
                        "task_complete. Only Planner may complete the overall task. "
                        "Summarize the current stage and handoff according to allowed_handoffs."
                    )
                    if supports_tools:
                        messages.append(format_tool_results(
                            control_call["id"], control_call["name"],
                            {"success": False, "error": error_msg},
                        ))
                    else:
                        messages.append({"role": "user", "content": error_msg})
                    save_session_state({
                        "activeAgentId": active_agent_id,
                        "messages": messages,
                        "stepCount": total_step_count,
                        "todoList": todo_tracker.get_all_tasks(),
                "planState": plan_state.to_serializable(),
                    })
                    continue

                summary = str(control_call["arguments"].get("summary") or "")
                if supports_tools:
                    messages.append(format_tool_results(
                        control_call["id"], control_call["name"],
                        {"success": True, "output": summary},
                    ))
                save_session_state({
                    "activeAgentId": active_agent_id,
                    "messages": messages,
                    "stepCount": total_step_count,
                    "todoList": todo_tracker.get_all_tasks(),
                "planState": plan_state.to_serializable(),
                    "completionSummary": summary,
                })
                event_bus.emit("engine:end", {
                    "session_id": sid,
                    "reason": "completed",
                    "total_steps": total_step_count,
                    "summary": summary,
                })
                flush_pending_save()
                return {
                    "reason": "completed",
                    "total_steps": total_step_count,
                    "summary": summary,
                    "replan_count": plan_state.replan_count,
                    "decision_count": len(plan_state.decision_history),
                }

            if control_call is not None and control_call["name"] == "handoff_to_agent":
                args = control_call["arguments"]
                target = args.get("target_agent_id", "")
                reason = args.get("reason", "")
                task = args.get("task", "")

                try:
                    get_agent(target)
                except ValueError:
                    error_msg = f'Agent "{target}" does not exist.'
                    if supports_tools:
                        messages.append(format_tool_results(
                            control_call["id"], control_call["name"],
                            {"success": False, "error": error_msg},
                        ))
                    else:
                        messages.append({
                            "role": "user",
                            "content": f"[工具结果 handoff_to_agent]: {json.dumps({'error': error_msg})}",
                        })
                    continue

                if target not in agent.allowed_handoffs:
                    error_msg = (
                        f'Not allowed to handoff to "{target}". '
                        f"Allowed: [{', '.join(agent.allowed_handoffs)}]"
                    )
                    if supports_tools:
                        messages.append(format_tool_results(
                            control_call["id"], control_call["name"],
                            {"success": False, "error": error_msg},
                        ))
                    else:
                        messages.append({
                            "role": "user",
                            "content": f"[工具结果 handoff_to_agent]: {json.dumps({'error': error_msg})}",
                        })
                    continue

                if supports_tools:
                    messages.append(format_tool_results(
                        control_call["id"], control_call["name"],
                        {"success": True, "output": json.dumps({"target": target})},
                    ))
                else:
                    messages.append({
                        "role": "user",
                        "content": (
                            f"[工具结果 handoff_to_agent]: "
                            f"{json.dumps({'success': True, 'target': target})}"
                        ),
                    })

                prev_agent_id = active_agent_id
                active_agent_id = target
                plan_state.detector.record_handoff(total_step_count)
                event_bus.emit("agent:switch", {
                    "session_id": sid,
                    "from_agent_id": prev_agent_id,
                    "to_agent_id": active_agent_id,
                    "reason": reason,
                })
                save_session_state({
                    "activeAgentId": active_agent_id,
                    "messages": messages,
                    "stepCount": total_step_count,
                    "todoList": todo_tracker.get_all_tasks(),
                "planState": plan_state.to_serializable(),
                })
                messages.append({
                    "role": "user",
                    "content": f"[Handoff from {agent.name}]: {task}",
                })
                continue

            for tc in business_calls:
                event_bus.emit("tool:stream-start", {
                    "session_id": sid,
                    "tool_name": tc["name"],
                    "args": tc["arguments"],
                })

                result = await execute_tool(tc["name"], tc["arguments"], sid, agent.id)

                # 记录工具结果到 RePlan 检测器
                plan_state.detector.record_tool_call(
                    tc["name"],
                    success=result.get("success", False),
                    step=total_step_count,
                )
                if not result.get("success", False):
                    plan_state.add_failure(
                        agent_id=agent.id,
                        tool_name=tc["name"],
                        error=result.get("error", "Unknown error"),
                        step=total_step_count,
                    )

                event_bus.emit("tool:stream-end", {
                    "session_id": sid,
                    "tool_name": tc["name"],
                    "result": result.get("output") if result.get("success") else result.get("error"),
                })
                event_bus.emit("tool:result", {
                    "session_id": sid,
                    "agent_id": agent.id,
                    "tool_name": tc["name"],
                    "result": result.get("output") if result.get("success") else result.get("error"),
                })

                # 只有明确属于证据语义的工具结果才产出 Evidence;普通 Tool Result 不进 Evidence
                evidence_record = classify_tool_evidence(tc["name"], result)
                if evidence_record is not None:
                    event_bus.emit("engine:evidence", {
                        "session_id": sid,
                        "evidence": evidence_record,
                    })

                compacted = compact_tool_output(tc["name"], result)
                removed = max(
                    0,
                    estimate_tokens(json.dumps(result.get("output") or "", ensure_ascii=False))
                    - estimate_tokens(json.dumps(compacted.get("output") or "", ensure_ascii=False)),
                )
                event_bus.emit("context:compacted", {
                    "session_id": sid,
                    "removed_tokens": removed,
                    "tool_name": tc["name"],
                })

                if supports_tools:
                    messages.append(format_tool_results(tc["id"], tc["name"], compacted))
                else:
                    output_text = json.dumps(
                        (
                            {"success": True, "output": compacted.get("output")}
                            if compacted.get("success")
                            else {"success": False, "error": compacted.get("error")}
                        ),
                        ensure_ascii=False,
                    )
                    messages.append({
                        "role": "user",
                        "content": f"[工具结果 {tc['name']}]: {output_text}",
                    })

            save_session_state({
                "activeAgentId": active_agent_id,
                "messages": messages,
                "stepCount": total_step_count,
                "todoList": todo_tracker.get_all_tasks(),
                "planState": plan_state.to_serializable(),
            })

            if business_calls:
                continue

            # 无工具调用 → 纯文本输出,默认挂起等待用户输入
            if os.environ.get("SECGO_AUTO_CONTINUE") == "1":
                # 自动继续模式(headless/脚本):不挂起,将引擎文本回灌为 user 消息继续循环
                auto_input = (response.text or "").strip() + "\n请继续,若已完成请调用 task_complete."
                event_bus.emit("engine:user_input", {
                    "session_id": sid,
                    "input": auto_input,
                })
                messages.append({"role": "user", "content": auto_input})
                continue

            event_bus.emit("engine:awaiting_input", {
                "session_id": sid,
                "agent_id": agent.id,
                "message": response.text or "",
            })

            save_session_state({
                "activeAgentId": active_agent_id,
                "messages": messages,
                "stepCount": total_step_count,
                "todoList": todo_tracker.get_all_tasks(),
                "planState": plan_state.to_serializable(),
            })
            flush_pending_save()  # 挂起等待输入前落库,避免长挂起期间状态仅存于内存
            new_user_input = await _wait_for_user_input(sid)
            event_bus.emit("engine:user_input", {
                "session_id": sid,
                "input": new_user_input,
            })
            messages.append({"role": "user", "content": new_user_input})
            continue

        event_bus.emit("engine:end", {
            "session_id": sid,
            "reason": "max_steps",
            "total_steps": total_step_count,
        })
        save_session_state({
            "activeAgentId": active_agent_id,
            "messages": messages,
            "stepCount": total_step_count,
            "todoList": todo_tracker.get_all_tasks(),
                "planState": plan_state.to_serializable(),
        })
        return {"reason": "max_steps", "total_steps": total_step_count}
    finally:
        cancel_waiting_input(sid)
        flush_pending_save()  # 兜底:最后一步的 engine context 保存必须落库
        session_manager.close()