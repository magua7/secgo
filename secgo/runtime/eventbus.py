"""事件总线：mitt 风格的轻量发布/订阅（支持 '*' 通配订阅）。

通过 contextvar 记录当前引擎会话：emit 时若事件数据未携带 session_id，
自动从上下文补上（provider 层事件如 llm:stream/tool:call 因此也能被
Web 端按会话路由）。
"""

import contextvars
from typing import Any, Callable, Dict, List, Optional

Handler = Callable[[Dict[str, Any]], None]

_current_session: "contextvars.ContextVar[Optional[str]]" = contextvars.ContextVar(
    "secgo_session_id", default=None
)


def set_current_session(session_id: Optional[str]) -> None:
    _current_session.set(session_id)


class EventBus:
    def __init__(self) -> None:
        self._handlers: Dict[str, List[Handler]] = {}

    def on(self, event: str, handler: Handler) -> None:
        self._handlers.setdefault(event, []).append(handler)

    def off(self, event: str, handler: Handler) -> None:
        handlers = self._handlers.get(event)
        if handlers is not None and handler in handlers:
            handlers.remove(handler)

    def emit(self, event: str, data: Dict[str, Any]) -> None:
        merged = dict(data)
        if "session_id" not in merged:
            sid = _current_session.get()
            if sid is not None:
                merged["session_id"] = sid
        targets: List[Handler] = []
        targets.extend(self._handlers.get(event, []))
        targets.extend(self._handlers.get("*", []))
        for handler in targets:
            try:
                handler(merged)
            except Exception:
                # 事件回调异常不允许打断引擎主流程
                pass


event_bus = EventBus()
