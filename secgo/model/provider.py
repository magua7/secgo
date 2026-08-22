"""LLM Provider：openai / anthropic 双协议流式调用，统一输出结构。

内部统一使用 OpenAI 格式的消息与工具调用结构；anthropic 订阅在边界处转换。
"""

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..config.config import LOCAL_PROVIDER_PRESETS, get_config
from ..kernel.agents import AgentConfig
from ..runtime.eventbus import event_bus


@dataclass
class StreamAgentResponse:
    text: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    response_messages: List[Dict[str, Any]] = field(default_factory=list)


_openai_providers: Dict[str, Any] = {}
_anthropic_providers: Dict[str, Any] = {}


def _get_openai_provider(subscription: Any):
    from openai import AsyncOpenAI

    # 缓存键含 apiKey：同 baseURL 不同 Key 各自建客户端；None 用占位符与空串区分
    key = (
        subscription.baseURL,
        subscription.apiKey if subscription.apiKey is not None else "__none__",
    )
    if key not in _openai_providers:
        kwargs: Dict[str, Any] = {"base_url": subscription.baseURL}
        if subscription.apiKey:
            kwargs["api_key"] = subscription.apiKey
        _openai_providers[key] = AsyncOpenAI(**kwargs)
    return _openai_providers[key]


def _get_anthropic_provider(subscription: Any):
    from anthropic import AsyncAnthropic

    key = (
        subscription.baseURL,
        subscription.apiKey if subscription.apiKey is not None else "__none__",
    )
    if key not in _anthropic_providers:
        kwargs: Dict[str, Any] = {"base_url": subscription.baseURL}
        if subscription.apiKey:
            kwargs["api_key"] = subscription.apiKey
        _anthropic_providers[key] = AsyncAnthropic(**kwargs)
    return _anthropic_providers[key]


def _to_openai_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema") or {"type": "object", "properties": {}},
            },
        }
        for t in tools
    ]


def _to_anthropic_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "name": t["name"],
            "description": t.get("description", ""),
            "input_schema": t.get("input_schema") or {"type": "object", "properties": {}},
        }
        for t in tools
    ]


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(part.get("text", ""))
        return "".join(parts)
    return str(content)


# ── OpenAI 兼容协议流式调用 ────────────────────────────────


def _is_retryable_error(err: Exception) -> bool:
    """判断 base_url 变体 fallback 是否值得重试另一方向变体。

    只对「连接类」错误（网络错误、超时、404/连接拒绝）重试；
    鉴权失败（401/403）、请求格式错误（400）、模型业务错误等直接抛出，
    避免把真实错误静默掩盖后空转。
    """
    try:
        from openai import APIConnectionError, APITimeoutError, NotFoundError
    except Exception:
        APIConnectionError = APITimeoutError = NotFoundError = ()
    try:
        import httpx
    except Exception:
        httpx = None
    if isinstance(err, (APIConnectionError, APITimeoutError, NotFoundError)):
        return True
    if httpx is not None and isinstance(err, httpx.TransportError):
        return True
    return False


async def _stream_openai(
    agent: AgentConfig,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    system_prompt: str,
) -> StreamAgentResponse:
    subscription = get_config().llm.subscriptions[agent.subscription]
    from dataclasses import replace

    base_url = (subscription.baseURL or "").rstrip("/")
    client = _get_openai_provider(subscription)

    kwargs: Dict[str, Any] = {
        "model": agent.model_id,
        "messages": [{"role": "system", "content": system_prompt}] + messages,
        "stream": True,
        "temperature": get_config().llm.temperature,
        "max_tokens": get_config().llm.maxTokens,
    }
    if tools:
        kwargs["tools"] = _to_openai_tools(tools)

    # base_url 变体 fallback：兼容官方（无 /v1）与中转（需 /v1）两种形态。
    # 主端点请求失败时，自动尝试补/去 /v1 的变体，避免用户填错形态直接报错。
    variants = [base_url]
    if base_url:
        if not base_url.endswith(("/v1", "/v2", "/v3", "/v4", "/chat/completions")):
            variants.append(base_url + "/v1")
        else:
            stripped = "/".join(base_url.rstrip("/").split("/")[:-1]).rstrip("/")
            if stripped:
                variants.append(stripped)

    last_error: Optional[Exception] = None
    stream = None
    for candidate in variants:
        try:
            if candidate != base_url:
                # 变体 base_url 重建 client（缓存按 baseURL 分键，互不影响）
                variant_sub = replace(
                    subscription, baseURL=candidate
                )
                client = _get_openai_provider(variant_sub)
            stream = await client.chat.completions.create(**kwargs)
            break
        except Exception as err:
            if not _is_retryable_error(err):
                # 非连接类错误（鉴权/请求格式/模型业务错误）不尝试变体，直接抛出真实错误
                raise
            last_error = err
            continue
    if stream is None:
        raise last_error if last_error is not None else RuntimeError(
            f"OpenAI request failed for base_url: {base_url}"
        )

    full_text = ""
    tool_calls: Dict[int, Dict[str, Any]] = {}

    def _flush_tool_call(call: Dict[str, Any], index: int) -> Dict[str, Any]:
        raw_args = call.get("arguments", "")
        try:
            args = json.loads(raw_args) if raw_args else {}
        except Exception:
            args = {"_raw": raw_args}
        return {
            "tool_call_id": call.get("id") or f"call_{index}",
            "tool_name": call.get("name") or "",
            "input": args,
        }

    async for chunk in stream:
        choices = getattr(chunk, "choices", None)
        if not choices:
            continue
        delta = choices[0].delta if choices[0] else None
        if delta is None:
            continue
        if delta.content:
            full_text += delta.content
            event_bus.emit("llm:stream", {"agent_id": agent.id, "chunk": delta.content})
        for tc_delta in delta.tool_calls or []:
            idx = tc_delta.index or 0
            slot = tool_calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
            if tc_delta.id:
                slot["id"] = tc_delta.id
            if tc_delta.function:
                if tc_delta.function.name:
                    slot["name"] += tc_delta.function.name
                if tc_delta.function.arguments:
                    slot["arguments"] += tc_delta.function.arguments

    # 流结束后统一归一化工具调用（无论 finish_reason 是 tool_calls 还是 stop）
    normalized_calls = [_flush_tool_call(c, idx) for idx, c in sorted(tool_calls.items())]
    for call in normalized_calls:
        event_bus.emit("tool:call", {
            "agent_id": agent.id,
            "tool_name": call["tool_name"],
            "args": call["input"],
        })

    # 200 但流式解析结果为空 → 端点是官方/中转形态不匹配（如返回 HTML 空页），不能当成功返回
    if not full_text and not normalized_calls:
        err_suffix = f"原始错误: {last_error}" if last_error else "无 HTTP 异常（服务端返回 200 但无内容）"
        raise RuntimeError(
            f"base_url 变体返回空响应，疑似官方/中转 URL 形态不匹配，{err_suffix}"
        )

    response_messages: List[Dict[str, Any]] = []
    assistant_msg: Dict[str, Any] = {"role": "assistant", "content": full_text or None}
    if normalized_calls:
        assistant_msg["tool_calls"] = [
            {
                "id": c["tool_call_id"],
                "type": "function",
                "function": {
                    "name": c["tool_name"],
                    "arguments": json.dumps(c["input"], ensure_ascii=False),
                },
            }
            for c in normalized_calls
        ]
    response_messages.append(assistant_msg)

    return StreamAgentResponse(
        text=full_text, tool_calls=normalized_calls, response_messages=response_messages
    )


# ── Anthropic 协议流式调用 ─────────────────────────────────


def _to_anthropic_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if role == "user":
            result.append({"role": "user", "content": _content_to_text(content)})
        elif role == "assistant":
            blocks: List[Dict[str, Any]] = []
            text = _content_to_text(content)
            if text:
                blocks.append({"type": "text", "text": text})
            for tc in msg.get("tool_calls") or []:
                try:
                    args = json.loads(tc["function"]["arguments"])
                except Exception:
                    args = {}
                blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id") or f"call_{len(blocks)}",
                    "name": tc["function"]["name"],
                    "input": args,
                })
            result.append({
                "role": "assistant",
                "content": blocks or [{"type": "text", "text": ""}],
            })
        elif role == "tool":
            result.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id", ""),
                    "content": _content_to_text(content),
                }],
            })
    return result


async def _stream_anthropic(
    agent: AgentConfig,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    system_prompt: str,
) -> StreamAgentResponse:
    subscription = get_config().llm.subscriptions[agent.subscription]
    client = _get_anthropic_provider(subscription)

    kwargs: Dict[str, Any] = {
        "model": agent.model_id,
        "system": system_prompt,
        "messages": _to_anthropic_messages(messages),
        "max_tokens": get_config().llm.maxTokens,
    }
    if tools:
        kwargs["tools"] = _to_anthropic_tools(tools)

    full_text = ""
    tool_calls: List[Dict[str, Any]] = []

    async with client.messages.stream(**kwargs) as stream:
        async for text_delta in stream.text_stream:
            full_text += text_delta
            event_bus.emit("llm:stream", {"agent_id": agent.id, "chunk": text_delta})
        final = await stream.get_final_message()
        for block in final.content:
            if block.type == "tool_use":
                tool_calls.append({
                    "tool_call_id": block.id,
                    "tool_name": block.name,
                    "input": dict(block.input) if isinstance(block.input, dict) else {},
                })
                event_bus.emit("tool:call", {
                    "agent_id": agent.id,
                    "tool_name": block.name,
                    "args": dict(block.input) if isinstance(block.input, dict) else {},
                })

    assistant_msg: Dict[str, Any] = {"role": "assistant", "content": full_text or None}
    if tool_calls:
        assistant_msg["tool_calls"] = [
            {
                "id": c["tool_call_id"],
                "type": "function",
                "function": {
                    "name": c["tool_name"],
                    "arguments": json.dumps(c["input"], ensure_ascii=False),
                },
            }
            for c in tool_calls
        ]
    return StreamAgentResponse(
        text=full_text, tool_calls=tool_calls, response_messages=[assistant_msg]
    )


# ── 统一入口 ──────────────────────────────────────────────


def _resolve_subscription(agent: AgentConfig):
    subscription = get_config().llm.subscriptions.get(agent.subscription)
    if subscription is None:
        raise ValueError(
            f'Subscription "{agent.subscription}" not configured for agent "{agent.id}"'
        )
    return subscription


async def stream_agent_response(
    agent: AgentConfig,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    override_system_prompt: Optional[str] = None,
) -> StreamAgentResponse:
    subscription = _resolve_subscription(agent)
    system_prompt = override_system_prompt or agent.system_prompt

    if subscription.provider.strip().lower() == "anthropic":
        return await _stream_anthropic(agent, messages, tools, system_prompt)

    # openai / ollama / lm-studio：OpenAI 兼容协议
    provider_key = subscription.provider.strip().lower()
    if provider_key in ("ollama", "lm-studio"):
        preset = LOCAL_PROVIDER_PRESETS[provider_key]
        from dataclasses import replace

        subscription = replace(
            subscription, baseURL=subscription.baseURL or preset["baseURL"]
        )
    return await _stream_openai(agent, messages, tools, system_prompt)


# ── 摘要生成（非流式） ─────────────────────────────────────

_SUMMARY_SYSTEM = """你是一个对话摘要生成器。请将以下对话历史压缩为一段结构化摘要。
摘要必须包含以下部分：
- [已完成] 已经完成的任务和操作
- [关键发现] 重要的发现、结果或数据
- [待处理] 尚未完成或需要继续的任务
- [重要决策] 做出的关键决策和原因

要求：简洁、信息密度高，不超过 500 字。直接输出摘要内容，不要加额外说明。"""


async def generate_summary(
    messages: List[Dict[str, Any]], subscription: Optional[str] = None
) -> str:
    config = get_config()

    sub_key = subscription or "coding"
    resolved = config.llm.subscriptions.get(sub_key)
    if resolved is None:
        raise ValueError(f'Subscription "{sub_key}" not found for summary')

    if config.context.summaryModel is not None:
        model_id = config.context.summaryModel
    else:
        model_id = resolved.modelId or config.llm.defaultModel

    text_parts: List[str] = []
    for msg in messages:
        role = msg.get("role")
        if role in ("user", "assistant"):
            content = msg.get("content")
            if isinstance(content, str):
                text_parts.append(f"[{role}]: {content}")
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text_parts.append(f"[{role}]: {part.get('text', '')}")
    conversation_text = "\n".join(text_parts)

    if resolved.provider.strip().lower() == "anthropic":
        client = _get_anthropic_provider(resolved)
        resp = await client.messages.create(
            model=model_id,
            max_tokens=800,
            system=_SUMMARY_SYSTEM,
            messages=[{"role": "user", "content": f"请摘要以下对话历史：\n\n{conversation_text}"}],
        )
        return "".join(block.text for block in resp.content if block.type == "text")
    else:
        client = _get_openai_provider(resolved)
        resp = await client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": _SUMMARY_SYSTEM},
                {"role": "user", "content": f"请摘要以下对话历史：\n\n{conversation_text}"},
            ],
            max_tokens=800,
        )
        return resp.choices[0].message.content or ""
