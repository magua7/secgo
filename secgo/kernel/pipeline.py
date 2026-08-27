"""消息处理管线：工具调用归一化 / 结果格式化 / fallback / 压缩 / 摘要 / TODO。"""

import json
import re
from typing import Any, Dict, List, Optional

from ..config.config import get_config
from ..runtime.budget import estimate_messages_tokens, estimate_tokens

# ── 归一化与格式化 ────────────────────────────────────────


def normalize_tool_calls(raw_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "id": tc.get("toolCallId") or tc.get("id") or f"call_{i}",
            "name": tc.get("toolName") or tc.get("name") or "",
            "arguments": tc.get("input") or tc.get("arguments") or {},
        }
        for i, tc in enumerate(raw_calls)
    ]


def format_tool_results(
    tool_call_id: str, tool_name: str, result: Dict[str, Any]
) -> Dict[str, Any]:
    payload = (
        {"success": True, "output": result.get("output")}
        if result.get("success")
        else {"success": False, "error": result.get("error")}
    )
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": json.dumps(payload, ensure_ascii=False),
    }


# ── fallback：不支持原生工具调用的模型 ──────────────────────


def inject_tools_to_prompt(tools: List[Dict[str, Any]], system_prompt: str) -> str:
    if not tools:
        return system_prompt
    descriptions = "\n".join(
        f"{i + 1}. **{t['name']}**: {t.get('description', '')}"
        for i, t in enumerate(tools)
    )
    return f"""{system_prompt}

## 可用工具

你可以使用以下工具。要调用工具，请在回复中使用以下格式：
```tool_call
{{"name": "工具名", "arguments": {{"参数名": "参数值"}}}}
```

{descriptions}

调用工具后，等待工具返回结果再继续。"""


def parse_tool_calls_from_text(text: str) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []
    pattern = re.compile(r"```tool_call\s*\n(.*?)\n```", re.DOTALL)
    for i, match in enumerate(pattern.finditer(text)):
        try:
            parsed = json.loads(match.group(1))
            if isinstance(parsed, dict) and parsed.get("name"):
                calls.append({
                    "id": f"fallback_{i}",
                    "name": parsed["name"],
                    "arguments": parsed.get("arguments") or {},
                })
        except Exception:
            continue
    return calls


# ── 工具输出压缩 ──────────────────────────────────────────

FILE_READ_TOOLS = {"read_file", "read_from_workspace", "read_file_from_workspace"}
COMMAND_EXEC_TOOLS = {"execute_bash"}
SEARCH_TOOLS = {"web_search", "grep"}
WRITE_TOOLS = {"write_to_workspace", "edit_file", "write_file"}


def _output_to_string(output: Any) -> str:
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    return json.dumps(output, ensure_ascii=False)


def _omit_marker(count: int, unit: str) -> str:
    return f"\n\n[... 省略 {count} {unit}，内容已处理 ...]\n\n"


def _fold_by_lines(text: str, head: int, tail: int) -> str:
    lines = text.split("\n")
    if len(lines) <= head + tail:
        return text
    omitted = len(lines) - head - tail
    return "\n".join(lines[:head]) + _omit_marker(omitted, "行") + "\n".join(lines[-tail:])


def _truncate_chars(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + _omit_marker(len(text) - max_chars, "字符")


def _truncate_search_results(text: str, max_items: int, max_chars: int) -> str:
    blocks = re.split(r"\n(?=\d+[\.\)、])|\n(?=- )|\n(?=▶)", text)
    if len(blocks) <= 1:
        return _truncate_chars(text, max_items * max_chars)
    kept = [_truncate_chars(b, max_chars) for b in blocks[:max_items]]
    omitted = len(blocks) - max_items
    result = "\n".join(kept)
    if omitted > 0:
        result += _omit_marker(omitted, "条结果")
    return result


def compact_tool_output(
    tool_name: str, result: Dict[str, Any], max_tokens: Optional[int] = None
) -> Dict[str, Any]:
    limit = max_tokens if max_tokens is not None else get_config().context.toolOutputMaxTokens
    output = result.get("output")
    if output is None or output == "":
        return result
    text = _output_to_string(output)
    if estimate_tokens(text) <= limit:
        return result

    if tool_name in FILE_READ_TOOLS:
        compacted = _fold_by_lines(text, 30, 10)
    elif tool_name in COMMAND_EXEC_TOOLS:
        compacted = _fold_by_lines(text, 50, 20)
    elif tool_name in SEARCH_TOOLS:
        compacted = _truncate_search_results(text, 3, 200)
    elif tool_name in WRITE_TOOLS:
        first_line = text.split("\n")[0] if text else ""
        compacted = _truncate_chars(first_line, 200)
    else:
        compacted = _truncate_chars(text, limit * 4)

    new_result: Dict[str, Any] = {"success": result.get("success", False), "output": compacted}
    if result.get("error") is not None:
        new_result["error"] = result["error"]
    return new_result


def compact_old_tool_results(
    messages: List[Dict[str, Any]], keep_recent: Optional[int] = None
) -> List[Dict[str, Any]]:
    keep = keep_recent if keep_recent is not None else get_config().context.slidingWindowSize
    indices_to_compact: set[int] = set()
    tool_result_count = 0
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.get("role") == "tool":
            tool_result_count += 1
            if tool_result_count > keep:
                indices_to_compact.add(i)
        elif (
            msg.get("role") == "user"
            and isinstance(msg.get("content"), str)
            and msg["content"].startswith("[工具结果")
        ):
            tool_result_count += 1
            if tool_result_count > keep:
                indices_to_compact.add(i)
    if not indices_to_compact:
        return messages

    result: List[Dict[str, Any]] = []
    for idx, msg in enumerate(messages):
        if idx not in indices_to_compact:
            result.append(msg)
            continue
        role = msg.get("role")
        if role == "tool":
            new_msg = dict(msg)
            new_msg["content"] = "[content omitted, already processed]"
            result.append(new_msg)
        elif isinstance(msg.get("content"), str):
            match = re.match(r"^\[工具结果\s+(\S+)", msg["content"])
            tool_name = match.group(1) if match else "unknown"
            new_msg = dict(msg)
            new_msg["content"] = f"[工具结果 {tool_name}: content omitted, already processed]"
            result.append(new_msg)
        else:
            result.append(msg)
    return result


# ── 摘要压缩 ──────────────────────────────────────────────


def should_summarize(messages: List[Dict[str, Any]]) -> bool:
    config = get_config()
    token_count = estimate_messages_tokens(messages)
    threshold = config.context.contextWindow * config.context.summaryThreshold
    return token_count > threshold


def _fallback_summary(messages: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for i in range(0, len(messages), 5):
        msg = messages[i]
        content = msg.get("content")
        text = content[:100] if isinstance(content, str) else f"[{msg.get('role', '')}消息]"
        parts.append(text)
    return f"早期对话概要：{'；'.join(parts)}"


async def summarize_messages(
    messages: List[Dict[str, Any]], subscription: Optional[str] = None
) -> str:
    from ..model.provider import generate_summary

    try:
        return await generate_summary(messages, subscription)
    except Exception:
        return _fallback_summary(messages)


async def compact_messages_with_summary(
    messages: List[Dict[str, Any]], precomputed_summary: Optional[str] = None
) -> List[Dict[str, Any]]:
    from ..model.provider import generate_summary

    config = get_config()
    window_size = config.context.slidingWindowSize

    head: List[Dict[str, Any]] = []
    if messages and messages[0].get("role") == "user":
        head.append(messages[0])

    tail_count = window_size * 2
    tail_start = max(len(head), len(messages) - tail_count)
    tail = messages[tail_start:]

    if tail_start <= len(head):
        return messages

    middle = messages[len(head):tail_start]

    summary_text: str
    if precomputed_summary is not None:
        summary_text = precomputed_summary
    else:
        try:
            summary_text = await generate_summary(middle)
        except Exception:
            summary_text = _fallback_summary(middle)

    return head + [{"role": "user", "content": f"[历史摘要] {summary_text}"}] + tail


# ── TODO 追踪 ─────────────────────────────────────────────

_TODO_RE = re.compile(r"- \[([ xX])\] (.+)")
# 内部控制工具名（task_complete / handoff_to_agent）属于引擎协议事件，
# 不应作为用户任务项进入 TODO（Planner 收尾时可能写出「最终汇报并 task_complete」这类行）
_INTERNAL_CONTROL_RE = re.compile(r"\bhandoff_to_agent\b|\btask[\s_-]*complete\b", re.IGNORECASE)


class TodoTracker:
    def __init__(self) -> None:
        self._tasks: List[Dict[str, Any]] = []

    def extract_todo_from_text(self, text: str) -> List[Dict[str, Any]]:
        return [
            {"text": match.group(2), "done": match.group(1) != " "}
            for match in _TODO_RE.finditer(text)
            if not _INTERNAL_CONTROL_RE.search(match.group(2))
        ]

    def update_todo(self, tasks: List[Dict[str, Any]]) -> None:
        self._tasks = list(tasks)

    def get_formatted_todo(self) -> str:
        if not self._tasks:
            return ""
        lines = [f"- [{'x' if t['done'] else ' '}] {t['text']}" for t in self._tasks]
        return f"[当前任务追踪]\n" + "\n".join(lines)

    def get_all_tasks(self) -> List[Dict[str, Any]]:
        return list(self._tasks)

    def restore(self, tasks: List[Dict[str, Any]]) -> None:
        self._tasks = list(tasks)
