"""SEC-GO Web 形态：FastAPI + SSE 事件流 + 单文件前端。

安全流程（三态状态机）：
  [A 未登录] → 登录 → [B 已登录] → 个人设置页配置模型 → [C 已就绪可对话]
  登录凭据与模型配置（含 API Key）全部持久化到 settings.json web/llm/subscriptions/agents 节。

API：
- POST /api/login                    (密码) → 签发 Cookie
- POST /api/logout                   → 清除 Cookie（settings.json 配置保留）
- POST /api/setup-keys               (default/planner 模型配置) → 写入 settings.json
- GET  /api/keys-status              → 返回掩码模型配置状态（无明文）
- POST /api/chat                     (需登录+模型就绪) 启动引擎会话
- GET  /api/events                   (需登录+模型就绪) SSE
- GET  /api/sessions                 (需登录+模型就绪)
- GET  /api/sessions/{id}/messages   (需登录+模型就绪)
- ...其他 /api/*                     (需登录+模型就绪)
- GET  /     → 未登录 login.html；已登录 setup.html（未就绪）或 index.html
- GET  /login  /setup
"""

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
import time
import uuid
import webbrowser
from collections import deque
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Cookie
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel

from ..config.config import DEFAULT_AGENT_THINKING, SETTINGS_FILE, get_config, reset_config
from ..config.jsonc import parse_jsonc, stringify_jsonc
from ..kernel.handoff_engine import (
    cancel_waiting_input,
    is_engine_awaiting_input,
    provide_user_input,
    run_engine,
)
from ..runtime.attachments import (
    MAX_ATTACHMENT_BYTES,
    MAX_ATTACHMENTS_PER_TASK,
    MAX_TASK_ATTACHMENT_BYTES,
    cleanup_expired_temporary_attachments,
    extract_limited_text,
    get_session_attachment_path,
    get_temporary_attachment,
    move_attachment_to_session,
    save_temporary_attachment,
)
from ..runtime.eventbus import event_bus
from ..runtime.session import SessionManager, resolve_session_db_path
from ..runtime import turn_manager

STATIC_DIR = Path(__file__).resolve().parent / "static"
RING_BUFFER_SIZE = 2000


def _page_response(name: str) -> FileResponse:
    """返回单文件前端页面并禁止浏览器缓存。

    登录页挂在 / 下，登录成功后前端 window.location.assign('/') 跳回同一 URL；
    若不禁止缓存，浏览器会直接复用缓存的 login.html 而不回源，导致登录后永远停在登录页。
    """
    resp = FileResponse(str(STATIC_DIR / name))
    resp.headers["Cache-Control"] = "no-store"
    return resp
HEARTBEAT_SECONDS = 15
CHANNEL_IDLE_CLEANUP_SECONDS = 300  # SSE 断线后保留通道的时长（防内存累积）

# 重连补发历史（ring）对大文本字段的截断：超过 2KB 截断为前 2KB 并追加标记
_RING_TRUNCATE_CHARS = 2 * 1024
_RING_TRUNCATE_MARKER = "…[已截断]"
# 各事件中可能含大文本的字段（tool:stream-start 的 args 为参数对象，递归截断其字符串值）
_RING_TRUNCATE_FIELDS = {
    "tool:result": "result",
    "tool:stream-end": "result",
    "engine:text": "text",
    "tool:stream-start": "args",
}


def _truncate_text(value: Any, limit: int) -> Any:
    """递归截断字符串值：超过 limit 保留前 limit 字符并追加截断标记。"""
    if isinstance(value, str):
        if len(value) <= limit:
            return value
        return value[:limit] + _RING_TRUNCATE_MARKER
    if isinstance(value, dict):
        new = {k: _truncate_text(v, limit) for k, v in value.items()}
        return new if new != value else value
    if isinstance(value, list):
        new = [_truncate_text(v, limit) for v in value]
        return new if new != value else value
    return value


def _truncate_for_ring(event: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """重连补发用截断副本：仅命中大文本字段的事件复制并截断，其余原样（与现状共享 data）。"""
    field = _RING_TRUNCATE_FIELDS.get(event)
    if field is None:
        return data
    value = data.get(field)
    if value is None:
        return data
    truncated = _truncate_text(value, _RING_TRUNCATE_CHARS)
    if truncated is value:
        return data
    copy = dict(data)
    copy[field] = truncated
    return copy

app = FastAPI(title="SEC-GO Web", version="1.0.0")


# ── 鉴权 & 会话 Cookie ─────────────────────────────────────

AUTH_COOKIE = "secgo_session"
AUTH_TTL_SECONDS = 24 * 3600  # 会话 24 小时（配置持久化在 settings.json，不会过期）
FIXED_WEB_PASSWORD = "secgo123"
FIXED_WEB_PASSWORD_HASH = hashlib.sha256(FIXED_WEB_PASSWORD.encode()).hexdigest()
# 登录态只在本次 Web 服务进程内有效；重启 web.bat 后旧 Cookie 自动失效。
_AUTH_BOOT_ID = secrets.token_urlsafe(32)


def _web_credentials() -> tuple:
    """从 settings.json web 节动态读取 Web 凭据（惰性单例，避免模块加载时序问题）。"""
    web = get_config().web
    return (
        web.secretKey or "dev-insecure-secret-change-me-xxxxxxxxxxxxxxxxx",
        FIXED_WEB_PASSWORD_HASH,
        "",
    )


def _sign(s: str) -> str:
    secret_key, _, _ = _web_credentials()
    payload = f"{_AUTH_BOOT_ID}:{s}"
    return hmac.new(secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()


def _make_session_token() -> str:
    exp = str(int(time.time() + AUTH_TTL_SECONDS))
    return f"{exp}.{_sign(exp)}"


def _verify_session_token(tok: Optional[str]) -> bool:
    if not tok or "." not in tok:
        return False
    exp_s, sig = tok.split(".", 1)
    try:
        if int(exp_s) < int(time.time()):
            return False
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(sig, _sign(exp_s))


def _auth_enabled() -> bool:
    """固定使用 SEC-GO Web 登录密码。"""
    _, admin_pwd_hash, admin_pwd_plain = _web_credentials()
    return bool(admin_pwd_hash) or bool(admin_pwd_plain)


def _password_matches(input_pwd: str) -> bool:
    _, admin_pwd_hash, admin_pwd_plain = _web_credentials()
    if admin_pwd_hash:
        inp = hashlib.sha256((input_pwd or "").encode()).hexdigest()
        return hmac.compare_digest(inp, admin_pwd_hash)
    if admin_pwd_plain:
        return hmac.compare_digest(input_pwd or "", admin_pwd_plain)
    return False


def _is_logged_in(secgo_session: Optional[str]) -> bool:
    if not _auth_enabled():
        return False
    return _verify_session_token(secgo_session)


async def require_logged_in(secgo_session: Optional[str] = Cookie(None, alias=AUTH_COOKIE)):
    """依赖：要求已登录（不要求已设置 Key）。用于 /api/setup-keys 等。"""
    if not _is_logged_in(secgo_session):
        raise HTTPException(status_code=401, detail="Login required")


def _config_ready() -> bool:
    """模型配置就绪检查：llm 启用 + 默认订阅与所有 Agent 绑定订阅三要素齐全。"""
    cfg = get_config()
    if not cfg.llm.enabled or not cfg.llm.subscriptions:
        return False

    def _complete(sub_name: str) -> bool:
        sub = cfg.llm.subscriptions.get(sub_name)
        return bool(sub and sub.baseURL and sub.apiKey and sub.modelId)

    default_name = "coding" if "coding" in cfg.llm.subscriptions else next(iter(cfg.llm.subscriptions))
    if not _complete(default_name):
        return False
    for agent_cfg in cfg.llm.agents.values():
        if agent_cfg.subscription and not _complete(agent_cfg.subscription):
            return False
    return True


async def require_ready_state(secgo_session: Optional[str] = Cookie(None, alias=AUTH_COOKIE)):
    """依赖：已登录 + 模型配置就绪。用于 /api/chat 等核心对话 API。"""
    if not _is_logged_in(secgo_session):
        raise HTTPException(status_code=401, detail="Login required")
    if not _config_ready():
        raise HTTPException(status_code=403, detail="模型尚未配置，请点击右上角 ⚙ 打开设置完成配置")


# ── 会话通道 ──────────────────────────────────────────────


class SessionChannel:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=RING_BUFFER_SIZE)
        self.ring: deque = deque(maxlen=RING_BUFFER_SIZE)
        self.seq = 0
        self.connections = 0  # 当前活跃 SSE 连接数（用于空闲清理）

    def push(self, event: str, data: Dict[str, Any]) -> None:
        self.seq += 1
        # ring 存截断副本（重连补发历史），queue 存原样 data（实时推送完整不变）
        self.ring.append((self.seq, event, _truncate_for_ring(event, data)))
        try:
            self.queue.put_nowait((self.seq, event, data))
        except asyncio.QueueFull:
            pass


_channels: Dict[str, SessionChannel] = {}
# 多个会话可同时挂起等待用户输入（多窗口隔离）：按 session_id 记录，而非全局单值
_awaiting_sessions: set = set()
# 每个会话当前正在运行的引擎任务（用于终止操作）
_tasks: Dict[str, asyncio.Task] = {}
_started = False


def _last_event_is_terminal(channel: SessionChannel) -> bool:
    """ring 最新事件是否为终止/挂起态，用于判断引擎是否已正常收尾。"""
    if not channel.ring:
        return False
    _, event, _ = channel.ring[-1]
    return event in ("engine:end", "engine:awaiting_input")


def _make_done_cb(session_id: str, channel: SessionChannel):
    """run_engine 任务结束后的清理与兜底补发。

    引擎异常崩溃时不会 emit engine:end（引擎 try/finally 无 except），
    若此时前端还锁着输入框会永久卡死——这里补发一个 end 事件解锁。
    """
    def cb(task: asyncio.Task) -> None:
        # identity check：只删当前 task 自己注册的引用，绝不误删之后注册的新任务
        if _tasks.get(session_id) is task:
            _tasks.pop(session_id, None)
        cancel_waiting_input(session_id)
        if task.cancelled():
            return  # 终止由 cancel 端点主动推送 engine:end(cancelled)
        exc = task.exception()
        if exc is not None and not _last_event_is_terminal(channel):
            # 走 event_bus：既推送 SSE channel，又让 TurnRecorder 收尾当前 Turn
            event_bus.emit("engine:end", {
                "session_id": session_id,
                "reason": "crashed",
                "total_steps": 0,
                "error": str(exc)[:300],
            })
    return cb


def _session_busy(session_id: str) -> bool:
    """同一 Session 当前是否已有「未结束的独立 Run」（awaiting continuation 不算 busy）。

    awaiting_user 补充输入是合法 continuation，不能误判为并发新 Run。
    """
    if is_engine_awaiting_input(session_id):
        return False
    task = _tasks.get(session_id)
    return task is not None and not task.done()


def _ensure_started() -> None:
    global _started
    if _started:
        return
    _started = True

    def on_event(data: Dict[str, Any]) -> None:
        sid = data.get("session_id")
        if not sid:
            return
        channel = _channels.get(sid)
        if channel is None:
            return
        event_name = data.get("_event")
        # 给 SSE 事件标注 turn_id，前端据此把事件路由到正确的 Turn（而非仅靠 session 最新 Turn）
        turn_id = turn_manager.active_turn_id(sid)
        if turn_id and "turn_id" not in data:
            data = dict(data)
            data["turn_id"] = turn_id
        channel.push(event_name, data)

    def make_handler(event_name: str):
        def handler(data: Dict[str, Any]) -> None:
            data = dict(data)
            data["_event"] = event_name
            on_event(data)
        return handler

    for event_name in (
        "engine:start", "agent:thinking", "agent:switch", "tool:call",
        "tool:result", "llm:stream", "engine:text", "engine:end",
        "budget:exceeded", "engine:error", "todo:updated",
        "tool:stream-start", "tool:stream-end",
        # 挂起等输入/继续执行也必须推送：否则前端无感知，输入框会一直禁用
        "engine:awaiting_input", "engine:user_input",
        # 显式证据事件 + 持久化告警：前端只据此构造 Evidence / 提示保存失败
        "engine:evidence", "persistence:warning",
        # RePlan 决策理由事件：前端据此展示「为什么换策略」
        "decision:reason",
    ):
        event_bus.on(event_name, make_handler(event_name))

    def on_awaiting(data: Dict[str, Any]) -> None:
        global _awaiting_sessions
        sid = data.get("session_id")
        if sid:
            _awaiting_sessions.add(sid)

    def on_resume(data: Dict[str, Any]) -> None:
        global _awaiting_sessions
        sid = data.get("session_id")
        if sid:
            _awaiting_sessions.discard(sid)

    event_bus.on("engine:awaiting_input", on_awaiting)
    event_bus.on("engine:user_input", on_resume)
    event_bus.on("engine:end", on_resume)

    # ── MCP 生命周期初始化：Web 启动即拉起 MCP server（stdio/SSE） ──
    try:
        from ..tools.mcp_client import mcp_lifecycle
        if not mcp_lifecycle.is_running():
            servers = get_config().mcp.servers
            if servers or os.environ.get("MCP_SERVER_COMMAND"):
                loop = asyncio.get_running_loop()
                loop.create_task(mcp_lifecycle.start(servers))
    except Exception as exc:
        print(f"[MCP] Web 生命周期初始化跳过: {exc}")


def _get_channel(session_id: str) -> SessionChannel:
    channel = _channels.get(session_id)
    if channel is None:
        channel = SessionChannel(session_id)
        _channels[session_id] = channel
    return channel


async def _schedule_channel_cleanup(session_id: str, channel: SessionChannel) -> None:
    """SSE 断线后延迟清理空闲通道，防止多窗口长期运行内存累积。"""
    await asyncio.sleep(CHANNEL_IDLE_CLEANUP_SECONDS)
    current = _channels.get(session_id)
    if current is channel and channel.connections <= 0:
        del _channels[session_id]


# ── 三态页面 + 登录 / 登出 / 设置 Key API ───────────────


@app.get("/")
async def root(secgo_session: Optional[str] = Cookie(None, alias=AUTH_COOKIE)) -> Response:
    """首页分发：未登录→login，已登录→index（模型配置改为应用内设置面板，不再强制落地 setup）。"""
    if not _is_logged_in(secgo_session):
        return _page_response("login.html")
    return _page_response("index.html")


@app.get("/login")
async def login_page(secgo_session: Optional[str] = Cookie(None, alias=AUTH_COOKIE)) -> Response:
    if _is_logged_in(secgo_session):
        return RedirectResponse("/")
    return _page_response("login.html")


@app.get("/setup")
async def setup_page(secgo_session: Optional[str] = Cookie(None, alias=AUTH_COOKIE)) -> Response:
    """个人设置页：已登录即可随时进入（无论模型是否已配置）。"""
    if not _is_logged_in(secgo_session):
        return RedirectResponse("/login")
    return _page_response("setup.html")


@app.post("/api/login")
async def api_login(password: str = Form("")) -> JSONResponse:
    if not _auth_enabled():
        # 没设访问密码 → 直接给会话，进入应用首页
        resp = JSONResponse({"ok": True, "next": "/"})
        resp.set_cookie(
            key=AUTH_COOKIE, value=_make_session_token(),
            httponly=True, samesite="lax", max_age=AUTH_TTL_SECONDS, path="/",
        )
        return resp
    if not _password_matches(password):
        return JSONResponse({"ok": False, "error": "访问密码错误"}, status_code=401)
    resp = JSONResponse({"ok": True, "next": "/"})
    resp.set_cookie(
        key=AUTH_COOKIE, value=_make_session_token(),
        httponly=True, samesite="lax", max_age=AUTH_TTL_SECONDS, path="/",
    )
    return resp


@app.post("/api/logout")
async def api_logout() -> JSONResponse:
    """登出 = 清 Cookie（settings.json 中的模型配置保留，下次登录直接可用）。"""
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(AUTH_COOKIE, path="/")
    return resp


# ── 订阅有效性校验（保存前对用户填的 base_url + api_key 发起最小请求验证）────

def _validate_subscription(provider: str, base_url: str, api_key: str, model: str) -> tuple[bool, str]:
    try:
        import httpx  # 通过 langchain 依赖已引入
    except Exception:
        return True, ""  # 没有 httpx 就跳过校验
    try:
        if (provider or "").strip().lower() == "anthropic":
            url = f"{base_url.rstrip('/')}/v1/messages"
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            payload = {"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}
        else:
            url = f"{base_url.rstrip('/')}/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}"}
            payload = {"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}
        r = httpx.post(url, headers=headers, json=payload, timeout=15)
        if r.status_code == 200:
            return True, ""
        try:
            j = r.json()
            msg = j.get("error", {}).get("message") or j.get("message") or r.text
        except Exception:
            msg = r.text
        return False, f"HTTP {r.status_code}：{str(msg)[:200]}"
    except Exception as e:
        return False, f"网络异常：{e}"


# ── 模型配置设置 / 查询 API ─────────────────────────────────

def _clean_provider(provider: str) -> str:
    """Preserve the configured vendor label; unknown vendors use OpenAI-compatible dispatch."""
    return (provider or "openai").strip() or "openai"


MODEL_AGENT_IDS = ("planner", "research", "builder", "operator")
MODEL_AGENT_LABELS = {
    "planner": "Planner",
    "research": "Research",
    "builder": "Builder",
    "operator": "Operator",
}


class _KeySetupReq(BaseModel):
    default: Optional[Dict[str, Any]] = None
    agents: Optional[Dict[str, Dict[str, Any]]] = None
    planner: Optional[Dict[str, Any]] = None
    # 字段名用 validate_keys，避免覆盖 Pydantic BaseModel 内置 validate 方法（否则启动会 UserWarning）
    validate_keys: bool = True


class _AttachmentUploadReq(BaseModel):
    name: str
    mimeType: str = "application/octet-stream"
    data: str


def _save_model_config(default_cfg: Optional[Dict[str, Any]],
                       agent_configs: Optional[Dict[str, Any]],
                       validate_keys: bool) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Validate an in-memory Default/Agent candidate set, then persist it as one unit."""

    # 先读取持久化源，以便空输入安全复用真实 Key；绝不从掩码状态反推凭据。
    existing = {}
    try:
        existing = parse_jsonc(SETTINGS_FILE.read_text(encoding="utf-8")) or {}
    except OSError:
        pass

    def _stored_key(config_id: str) -> str:
        if config_id == "default":
            return str(
                ((existing.get("subscriptions") or {}).get("coding") or {}).get("apiKey")
                or (existing.get("llm") or {}).get("api_key")
                or ""
            )
        subscriptions = existing.get("subscriptions") or {}
        # Legacy Planner configurations may still point at a differently named subscription.
        if config_id == "planner":
            planner_agent = (existing.get("agents") or {}).get("planner") or {}
            legacy_name = planner_agent.get("subscription") or ""
            if legacy_name and legacy_name != "coding":
                active_key = (subscriptions.get(legacy_name) or {}).get("apiKey")
                if active_key:
                    return str(active_key)
        return str((subscriptions.get(config_id) or {}).get("apiKey") or "")

    def _normalize_agents() -> tuple[Dict[str, Dict[str, Any]], set[str]]:
        requests = {
            agent_id: {"enabled": False, "config": {}}
            for agent_id in MODEL_AGENT_IDS
        }
        # A missing/flat second argument is the legacy Default+Planner contract.
        if agent_configs is None:
            return requests, {"planner"}
        if "base_url" in agent_configs or "model" in agent_configs:
            requests["planner"] = {"enabled": True, "config": dict(agent_configs)}
            return requests, {"planner"}
        for agent_id in MODEL_AGENT_IDS:
            entry = agent_configs.get(agent_id)
            if entry is None:
                continue
            if not isinstance(entry, dict):
                requests[agent_id] = {
                    "enabled": True,
                    "config": {},
                    "error": f"{MODEL_AGENT_LABELS[agent_id]} 模型：配置格式无效",
                }
                continue
            if "enabled" in entry:
                enabled_value = entry.get("enabled")
                config_value = entry.get("config")
                request_error = None
                if not isinstance(enabled_value, bool):
                    request_error = f"{MODEL_AGENT_LABELS[agent_id]} 模型：enabled 必须为布尔值"
                if enabled_value is True and not isinstance(config_value, dict):
                    request_error = f"{MODEL_AGENT_LABELS[agent_id]} 模型：配置格式无效"
                requests[agent_id] = {
                    "enabled": enabled_value is True,
                    "config": dict(config_value) if isinstance(config_value, dict) else {},
                    "error": request_error,
                }
            else:
                requests[agent_id] = {"enabled": True, "config": dict(entry)}
        return requests, set(MODEL_AGENT_IDS)

    normalized_agents, managed_agent_ids = _normalize_agents()
    configs: Dict[str, Dict[str, Any]] = {"default": dict(default_cfg or {})}
    for agent_id in MODEL_AGENT_IDS:
        if normalized_agents[agent_id]["enabled"] or normalized_agents[agent_id].get("error"):
            configs[agent_id] = normalized_agents[agent_id]["config"]

    validation: Dict[str, Dict[str, Any]] = {}
    candidates: Dict[str, Dict[str, Any]] = {}
    has_new_key: Dict[str, bool] = {}

    for config_id, cfg in configs.items():
        label = "默认模型" if config_id == "default" else f"{MODEL_AGENT_LABELS[config_id]} 模型"
        provider = _clean_provider(str(cfg.get("provider") or "openai"))
        base_url = str(cfg.get("base_url") or "").strip()
        model = str(cfg.get("model") or "").strip()
        submitted_key = str(cfg.get("api_key") or "").strip()
        error = normalized_agents.get(config_id, {}).get("error")
        if not base_url or not model:
            error = error or f"{label}：base_url 与 model 不能为空"
        elif "*" in submitted_key:
            error = f"{label}：API Key 不能使用掩码值"
        effective_key = submitted_key or _stored_key(config_id)
        if error is None and not effective_key:
            error = f"{label}：API Key 不能为空"

        has_new_key[config_id] = bool(submitted_key)
        candidates[config_id] = {
            "provider": provider,
            "baseURL": base_url,
            "modelId": model,
            "apiKey": effective_key,
        }
        validation[config_id] = {"ok": error is None, "error": error}

    # A replacement candidate is always validated. Reused working keys follow validate_keys.
    for config_id, candidate in candidates.items():
        if not validation[config_id]["ok"]:
            continue
        if not (validate_keys or has_new_key[config_id]):
            continue
        ok, msg = _validate_subscription(
            candidate["provider"], candidate["baseURL"],
            candidate["apiKey"], candidate["modelId"],
        )
        if not ok:
            label = "默认模型" if config_id == "default" else f"{MODEL_AGENT_LABELS[config_id]} 模型"
            prefix = "新 API Key 校验失败" if has_new_key[config_id] else "校验失败"
            validation[config_id] = {"ok": False, "error": f"{label}{prefix}：{msg}"}

    failed_ids = [config_id for config_id, result in validation.items() if not result["ok"]]
    if failed_ids:
        first = failed_ids[0]
        failed_label = "默认模型" if first == "default" else f"{MODEL_AGENT_LABELS[first]} 配置"
        global_error = f"模型配置未保存，请检查 {failed_label}"
        return global_error, {
            "ok": False,
            "saved": False,
            "validation": validation,
            "error": global_error,
        }

    default_sub = candidates["default"]
    default_provider = default_sub["provider"]

    # 合并 subscriptions：保留既有订阅，写入 default（coding）
    subs = dict(existing.get("subscriptions") or {})
    subs["coding"] = default_sub

    agents = dict(existing.get("agents") or {})
    for agent_id in managed_agent_ids:
        request = normalized_agents[agent_id]
        if request["enabled"]:
            subs[agent_id] = candidates[agent_id]
            previous = agents.get(agent_id) or {}
            agents[agent_id] = {
                "subscription": agent_id,
                "modelId": candidates[agent_id]["modelId"],
                "thinkingLevel": previous.get("thinkingLevel") or DEFAULT_AGENT_THINKING[agent_id],
            }
            continue

        # Preserve a legacy Planner subscription under its semantic name before unbinding it.
        if agent_id == "planner" and "planner" not in subs:
            previous = agents.get("planner") or {}
            legacy_name = previous.get("subscription") or ""
            if legacy_name and legacy_name != "coding" and legacy_name in subs:
                subs["planner"] = dict(subs[legacy_name])
        agents.pop(agent_id, None)

    # 只更新 llm 相关键，保留 web / run_limits / 既有字段（timeout_seconds、max_response_bytes 等）
    llm_section = dict(existing.get("llm") or {})
    llm_section["enabled"] = True
    llm_section["provider"] = default_provider
    llm_section["base_url"] = default_sub["baseURL"]
    llm_section["api_key"] = default_sub["apiKey"]
    llm_section["model"] = default_sub["modelId"]

    updated = dict(existing)
    updated["llm"] = llm_section
    updated["subscriptions"] = subs
    # agents 恒写入（可为空 dict = 显式无自定义 Agent，防止遗留 LLMconfig.jsonc 重新注入）
    updated["agents"] = agents

    try:
        _write_settings_atomically(updated)
    except OSError as e:
        message = f"写入 settings.json 失败：{e}"
        return message, {"ok": False, "saved": False, "validation": validation, "error": message}

    reset_config()  # 下次 get_config() 重新加载，新配置立即生效
    return None, {"ok": True, "saved": True, "next": "/", "validation": validation}


def _write_settings_atomically(updated: Dict[str, Any]) -> None:
    """Flush a same-directory temporary file before replacing the live settings file."""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{SETTINGS_FILE.name}.",
        suffix=".tmp",
        dir=SETTINGS_FILE.parent,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as temp_file:
            temp_file.write(stringify_jsonc(updated))
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, SETTINGS_FILE)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


@app.post("/api/setup-keys")
async def api_setup_keys(req: _KeySetupReq,
                         _auth=Depends(require_logged_in)) -> JSONResponse:
    submitted_agents: Optional[Dict[str, Any]] = req.agents if req.agents is not None else req.planner
    err, body = _save_model_config(req.default, submitted_agents, req.validate_keys)
    if err:
        return JSONResponse(body or {"ok": False, "saved": False, "error": err}, status_code=400)
    return JSONResponse(body)


@app.get("/api/keys-status")
async def api_keys_status(_auth=Depends(require_logged_in)) -> JSONResponse:
    """Return backend-generated masks and explicit override state, never plaintext keys."""
    def mask(k: Optional[str]) -> str:
        if not k:
            return ""
        if len(k) <= 6:
            return "***"
        return k[:3] + "***" + k[-3:]

    cfg = get_config()
    default_sub = cfg.llm.subscriptions.get("coding") or (
        next(iter(cfg.llm.subscriptions.values())) if cfg.llm.subscriptions else None
    )

    try:
        raw_settings = parse_jsonc(SETTINGS_FILE.read_text(encoding="utf-8")) or {}
    except OSError:
        raw_settings = {}
    raw_agents = raw_settings.get("agents") or {}
    raw_subscriptions = raw_settings.get("subscriptions")

    def _sub_info(sub, *, enabled: bool, model: Optional[str] = None) -> Dict[str, Any]:
        key = str(sub.apiKey or "")
        return {
            "enabled": enabled,
            "provider": sub.provider,
            "base_url": sub.baseURL,
            "model": model or sub.modelId,
            "has_key": bool(key),
            "api_key_masked": mask(key),
        }

    def _raw_sub_info(sub: Dict[str, Any], *, enabled: bool, model: Optional[str] = None) -> Dict[str, Any]:
        key = str(sub.get("apiKey") or "")
        return {
            "enabled": enabled,
            "provider": sub.get("provider") or "openai",
            "base_url": sub.get("baseURL") or "",
            "model": model or sub.get("modelId") or "",
            "has_key": bool(key),
            "api_key_masked": mask(key),
        }

    agent_status: Dict[str, Optional[Dict[str, Any]]] = {}
    for agent_id in MODEL_AGENT_IDS:
        raw_agent = raw_agents.get(agent_id) or {}
        loaded_agent = cfg.llm.agents.get(agent_id)
        requested_sub_name = str(raw_agent.get("subscription") or "")
        enabled = bool(
            raw_agent
            and requested_sub_name
            and requested_sub_name != "coding"
            and loaded_agent
            and loaded_agent.subscription != "coding"
        )
        if agent_id == "planner" and requested_sub_name and requested_sub_name != "coding":
            saved_raw = (raw_subscriptions or {}).get(requested_sub_name) if isinstance(raw_subscriptions, dict) else None
            saved_loaded = cfg.llm.subscriptions.get(requested_sub_name)
        else:
            saved_raw = (raw_subscriptions or {}).get(agent_id) if isinstance(raw_subscriptions, dict) else None
            saved_loaded = cfg.llm.subscriptions.get(agent_id)
        if saved_raw is not None:
            agent_status[agent_id] = _raw_sub_info(
                saved_raw,
                enabled=enabled,
                model=(raw_agent.get("modelId") if enabled else None),
            )
        elif raw_subscriptions is None and saved_loaded is not None:
            # Compatibility with installations still loading LLMconfig.jsonc.
            agent_status[agent_id] = _sub_info(
                saved_loaded,
                enabled=enabled,
                model=(raw_agent.get("modelId") if enabled else None),
            )
        else:
            agent_status[agent_id] = None

    planner_status = agent_status["planner"]
    enabled_planner = planner_status if planner_status and planner_status["enabled"] else None

    return JSONResponse({
        "auth_enabled": _auth_enabled(),
        "ready": _config_ready(),
        "has_default": default_sub is not None,
        "default": _sub_info(default_sub, enabled=True) if default_sub else None,
        "agents": agent_status,
        # Backward-compatible fields for an older Settings frontend.
        "has_planner": enabled_planner is not None,
        "planner": enabled_planner,
    })


@app.post("/api/attachments")
async def api_upload_attachment(req: _AttachmentUploadReq,
                                _auth=Depends(require_logged_in)) -> JSONResponse:
    cleanup_expired_temporary_attachments()
    name = req.name.strip()
    mime_type = req.mimeType.strip() or "application/octet-stream"
    if not name or len(name) > 512 or len(mime_type) > 256:
        return JSONResponse({"ok": False, "error": "文件名无效"}, status_code=400)
    max_base64_chars = 4 * ((MAX_ATTACHMENT_BYTES + 2) // 3)
    if len(req.data) > max_base64_chars:
        return JSONResponse({"ok": False, "error": "单文件不能超过 10MB"}, status_code=413)
    try:
        data = base64.b64decode(req.data, validate=True)
    except (binascii.Error, ValueError):
        return JSONResponse({"ok": False, "error": "文件内容不是合法 Base64"}, status_code=400)
    try:
        metadata = save_temporary_attachment(name, mime_type, data)
    except ValueError as error:
        return JSONResponse({"ok": False, "error": str(error)}, status_code=413)
    return JSONResponse({
        "ok": True,
        "attachment": {
            "id": metadata.attachment_id,
            "name": metadata.original_name,
            "mimeType": metadata.mime_type,
            "kind": metadata.detected_kind,
            "size": metadata.size,
            "sha256": metadata.sha256,
        },
    })


def _attachment_presentation(metadata) -> Dict[str, Any]:
    """附件的展示形态（不含 SHA256/服务器路径等内部信息）。"""
    return {
        "id": metadata.attachment_id,
        "filename": metadata.original_name,
        "mimeType": metadata.mime_type,
        "kind": metadata.detected_kind,
        "size": metadata.size,
    }


def _attachment_prompt(session_id: str, attachments: list) -> str:
    sections = ["[用户附件]"]
    for index, metadata in enumerate(attachments, 1):
        lines = [
            f"附件 {index}：",
            f"- evidence_id: {metadata.attachment_id}",
            f"- 文件名: {json.dumps(metadata.original_name, ensure_ascii=False)}",
            f"- 类型: {metadata.detected_kind}",
            f"- 大小: {metadata.size} bytes",
            f"- SHA-256: {metadata.sha256}",
        ]
        if metadata.detected_kind in ("text", "pdf", "zip"):
            extracted = extract_limited_text(
                get_session_attachment_path(session_id, metadata.attachment_id),
                detected_kind=metadata.detected_kind,
            )
            if extracted is not None:
                lines.extend([
                    f"\n[附件 {index} 提取内容开始]",
                    extracted,
                    f"[附件 {index} 提取内容结束]",
                ])
            else:
                lines.append(f"- 状态: {metadata.detected_kind} 内容提取失败")
        elif metadata.detected_kind == "image":
            lines.append("- 状态: 文件已安全保存，本阶段暂未启用图片视觉分析")
        else:
            lines.append("- 状态: 文件已安全保存，本阶段仅登记元数据")
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


# ── 业务 API（全部 require_ready_state）────────────────────


@app.post("/api/chat")
async def api_chat(request: Request, _auth=Depends(require_ready_state)) -> JSONResponse:
    global _awaiting_sessions
    _ensure_started()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)

    message = (body.get("message") or "").strip()
    attachment_ids = body.get("attachments") or []
    if not isinstance(attachment_ids, list) or any(not isinstance(item, str) for item in attachment_ids):
        return JSONResponse({"error": "attachments must be an array of attachment IDs"}, status_code=400)
    if not message and not attachment_ids:
        return JSONResponse({"error": "message or attachment is required"}, status_code=400)
    if len(attachment_ids) > MAX_ATTACHMENTS_PER_TASK or len(set(attachment_ids)) != len(attachment_ids):
        return JSONResponse({"error": "一次任务最多允许 8 个不重复附件"}, status_code=400)

    session_id = body.get("sessionId") or str(uuid.uuid4())
    if attachment_ids:
        try:
            normalized_session_id = str(uuid.UUID(session_id))
        except (ValueError, AttributeError, TypeError):
            return JSONResponse({"error": "invalid sessionId"}, status_code=400)
        if normalized_session_id != session_id:
            return JSONResponse({"error": "invalid sessionId"}, status_code=400)

    temporary = []
    total_size = 0
    for attachment_id in attachment_ids:
        try:
            if str(uuid.UUID(attachment_id)) != attachment_id:
                raise ValueError
            metadata = get_temporary_attachment(attachment_id)
        except (ValueError, OSError, json.JSONDecodeError, TypeError):
            metadata = None
        if metadata is None:
            return JSONResponse({"error": f"attachment not found: {attachment_id}"}, status_code=400)
        total_size += metadata.size
        temporary.append(metadata)
    if total_size > MAX_TASK_ATTACHMENT_BYTES:
        return JSONResponse({"error": "一次任务附件总量不能超过 20MB"}, status_code=400)

    moved_attachments = []
    try:
        for metadata in temporary:
            moved_attachments.append(move_attachment_to_session(metadata.attachment_id, session_id))
    except (OSError, ValueError) as error:
        return JSONResponse({"error": f"附件关联会话失败：{error}"}, status_code=400)

    # display 与 engine input 分离：展示层只放用户真正看到的问题 + 结构化附件；
    # 内部 engine_message（含 evidence_id/SHA256/提取内容）绝不作为 display message。
    engine_message = message
    display_message = message
    display_attachments: list = []
    if moved_attachments:
        question = message or "请分析这些附件。"
        engine_message = f"{_attachment_prompt(session_id, moved_attachments)}\n\n用户问题：\n{question}"
        display_message = question
        display_attachments = [_attachment_presentation(m) for m in moved_attachments]
    channel = _get_channel(session_id)

    is_resume = is_engine_awaiting_input(session_id)
    _awaiting_sessions.discard(session_id)

    # 并发保护：同 Session 已有未结束的独立 Run（非 awaiting continuation）→ 拒绝启动第二个引擎
    if not is_resume and _session_busy(session_id):
        return JSONResponse({
            "ok": False,
            "code": "SESSION_BUSY",
            "message": "当前会话已有正在执行的安全任务，请等待完成或先停止当前任务。",
        }, status_code=409)

    turn_id = str(uuid.uuid4())
    db_path = resolve_session_db_path()
    manager = SessionManager(db_path)
    try:
        loaded = manager.load_state(session_id)
        is_new = loaded is None
        state = loaded or {}
        # 引擎上下文：续聊把新指令补进 engine messages（run_engine 加载时覆盖初值）
        msgs = list(state.get("messages") or [])
        msgs.append({"role": "user", "content": engine_message})
        state["messages"] = msgs
        manager.save_state(session_id, state)
        # 新建 Turn（多轮对话真相：每个 Turn 独立一行、独立 execution snapshot）
        sequence = manager.get_next_turn_sequence(session_id)
        manager.create_turn(
            session_id, turn_id, sequence,
            {"text": display_message, "attachments": display_attachments},
            kind="direct_response", status="running",
        )
        if is_new:
            manager.set_meta(session_id, title=display_message[:30])
    finally:
        manager.close()

    # 订阅事件流，把本次 Turn 的执行镜像为独立 snapshot（不覆盖其它 Turn）
    turn_manager.start_turn(session_id, turn_id)

    if is_resume and provide_user_input(session_id, engine_message):
        return JSONResponse({"sessionId": session_id, "turnId": turn_id, "accepted": True, "resumed": True})

    task = asyncio.get_running_loop().create_task(run_engine(engine_message, session_id))
    _tasks[session_id] = task
    task.add_done_callback(_make_done_cb(session_id, channel))
    return JSONResponse({"sessionId": session_id, "turnId": turn_id, "accepted": True, "resumed": False})


@app.post("/api/sessions/{session_id}/cancel")
async def api_cancel_session(session_id: str, _auth=Depends(require_ready_state)) -> JSONResponse:
    """终止正在运行的引擎任务：取消协程 + 推送 end 事件解锁前端 + 收尾当前 Turn。"""
    global _awaiting_sessions
    _awaiting_sessions.discard(session_id)
    waiting_cancelled = cancel_waiting_input(session_id)
    task = _tasks.get(session_id)
    cancelled = False
    if task is not None and not task.done():
        task.cancel()
        cancelled = True
    # 走 event_bus 推送：SSE channel 收到（带 turn_id），TurnRecorder 同时把当前 Turn 落 stopped 终态
    event_bus.emit("engine:end", {
        "session_id": session_id,
        "reason": "cancelled",
        "total_steps": 0,
    })
    return JSONResponse({"sessionId": session_id, "cancelled": cancelled or waiting_cancelled})


@app.get("/api/events")
async def api_events(request: Request, _auth=Depends(require_ready_state)) -> StreamingResponse:
    _ensure_started()
    session_id = request.query_params.get("sessionId") or ""
    if not session_id:
        return JSONResponse({"error": "sessionId is required"}, status_code=400)

    last_event_id_raw = (
        request.headers.get("last-event-id")
        or request.query_params.get("lastEventId")
        or "0"
    )
    try:
        last_event_id = int(last_event_id_raw)
    except ValueError:
        last_event_id = 0

    channel = _get_channel(session_id)

    def sse_pack(seq: int, event: str, data: Dict[str, Any]) -> str:
        payload = json.dumps(data, ensure_ascii=False)
        return f"id: {seq}\nevent: {event}\ndata: {payload}\n\n"

    async def event_stream():
        channel.connections += 1
        sent: set = set()
        try:
            # 断线重连：先补发 Last-Event-ID 之后的事件
            for seq, event, data in list(channel.ring):
                if seq > last_event_id and seq not in sent:
                    sent.add(seq)
                    yield sse_pack(seq, event, data)
            while True:
                if await request.is_disconnected():
                    break
                try:
                    seq, event, data = await asyncio.wait_for(
                        channel.queue.get(), timeout=HEARTBEAT_SECONDS
                    )
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                if seq in sent:
                    continue
                sent.add(seq)
                yield sse_pack(seq, event, data)
        finally:
            # 连接断开：减少计数，空闲通道延迟回收
            channel.connections -= 1
            if channel.connections <= 0:
                asyncio.get_running_loop().create_task(
                    _schedule_channel_cleanup(session_id, channel)
                )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            # 关键：无 Content-Length 的流式响应必须声明 chunked，
            # 否则 h11 认为 body 长度为 0，首个数据块（如心跳 ping）即报
            # "Too much data for declared Content-Length"
            "Transfer-Encoding": "chunked",
        },
    )


@app.get("/api/sessions")
async def api_sessions(_auth=Depends(require_ready_state)) -> JSONResponse:
    db_path = resolve_session_db_path()
    manager = SessionManager(db_path)
    try:
        meta_map = {m["sessionId"]: m for m in manager.list_meta()}
        sessions = []
        for s in manager.list_sessions():
            m = meta_map.get(s["id"], {})
            sessions.append({
                "id": s["id"],
                "title": m.get("title", ""),
                "messageCount": s["messageCount"],
                "stepCount": s["stepCount"],
                "status": s.get("status", "idle"),
                "createdAt": m.get("createdAt", 0),
                "updatedAt": m.get("updatedAt", 0),
            })
        # 按最近更新倒序展示
        sessions.sort(key=lambda x: x["updatedAt"], reverse=True)
        return JSONResponse({"sessions": sessions})
    finally:
        manager.close()


@app.put("/api/sessions/{session_id}/title")
async def api_rename_session(session_id: str, request: Request, _auth=Depends(require_ready_state)) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    title = (body.get("title") or "").strip()
    if not title:
        return JSONResponse({"error": "title is required"}, status_code=400)
    db_path = resolve_session_db_path()
    manager = SessionManager(db_path)
    try:
        manager.set_meta(session_id, title=title[:30])
        return JSONResponse({"sessionId": session_id, "title": title[:30]})
    finally:
        manager.close()


@app.delete("/api/sessions/{session_id}")
async def api_delete_session(session_id: str, _auth=Depends(require_ready_state)) -> JSONResponse:
    db_path = resolve_session_db_path()
    manager = SessionManager(db_path)
    try:
        manager.delete_session(session_id)
        return JSONResponse({"sessionId": session_id, "deleted": True})
    finally:
        manager.close()


def _legacy_turns_from_messages(messages: list) -> list:
    """旧会话（无 conversation_turns）兜底：从引擎 messages 粗粒度还原 turns。

    只还原真实用户提问（剥离内部 prompt），execution 置空（旧数据没有 per-turn snapshot）。
    """
    turns: list = []
    current_user: Optional[str] = None
    current_assistant: Optional[str] = None
    seq = 0

    def flush() -> None:
        nonlocal current_user, current_assistant, seq
        if current_user is not None:
            seq += 1
            turns.append({
                "id": f"legacy-{seq}",
                "sequence": seq,
                "kind": "direct_response",
                "userMessage": {"text": current_user, "attachments": []},
                "assistantAnswer": current_assistant,
                "execution": None,
                "status": "completed",
                "createdAt": None,
                "updatedAt": None,
            })
        current_user = None
        current_assistant = None

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        if role == "user":
            if content.startswith(("[系统提示", "[Handoff", "[工具结果")):
                continue
            text = content.split("用户问题：", 1)[1].strip() if "用户问题：" in content else content
            if text.startswith("[用户附件]"):
                continue
            flush()
            current_user = text
        elif role == "assistant":
            if content and current_assistant is None:
                current_assistant = content
    flush()
    return turns


@app.get("/api/sessions/{session_id}/messages")
async def api_session_messages(session_id: str, _auth=Depends(require_ready_state)) -> JSONResponse:
    db_path = resolve_session_db_path()
    manager = SessionManager(db_path)
    try:
        state = manager.load_state(session_id)
        if state is None:
            return JSONResponse({"error": "session not found"}, status_code=404)
        turns = manager.list_turns(session_id)
        if not turns:
            # 旧会话（无 conversation_turns）兜底
            turns = _legacy_turns_from_messages(state.get("messages") or [])
        status = manager.get_session_status(session_id)
        if status == "idle":
            status = state.get("status") or "idle"
        return JSONResponse({
            "sessionId": session_id,
            "status": status,
            "turns": turns,
        })
    finally:
        manager.close()


@app.get("/api/mcp-status")
async def api_mcp_status(_auth=Depends(require_ready_state)) -> JSONResponse:
    """MCP 服务器连接状态 + 工具清单（前端 MCP 状态页数据源）。"""
    from ..tools.mcp_client import mcp_lifecycle, mcp_client
    servers: list = []
    for server_name, entry in getattr(mcp_client, "_servers", {}).items():
        servers.append({
            "name": server_name,
            "connected": True,
            "tool_count": len(entry.get("tools") or []),
        })
    tools = [t["name"] for t in mcp_client.get_tools()]
    return JSONResponse({
        "running": mcp_lifecycle.is_running(),
        "connected": mcp_client.is_connected(),
        "server_count": len(servers),
        "servers": servers,
        "tool_count": len(tools),
        "tools": tools,
        "configured": len(get_config().mcp.servers) > 0 or bool(os.environ.get("MCP_SERVER_COMMAND")),
    })


@app.get("/favicon.ico")
async def favicon() -> Response:
    # 204 状态不应携带 body，否则 h11 判定 body 长度为 0，发送 body 即报错
    return Response(status_code=204)


# ── 启动 ──────────────────────────────────────────────────


def main() -> None:
    import uvicorn

    port = int(os.environ.get("SECGO_WEB_PORT") or get_config().web.port)
    no_browser = os.environ.get("SECGO_NO_BROWSER") == "1"

    if not no_browser:
        def open_browser() -> None:
            try:
                webbrowser.open(f"http://localhost:{port}")
            except Exception:
                pass

        threading.Timer(1.5, open_browser).start()

    print(f"SEC-GO Web 已启动: http://localhost:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")