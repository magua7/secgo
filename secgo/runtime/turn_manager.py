"""Web 层多轮 Turn 生命周期：把 SSE 事件镜像为每个 Turn 独立的 execution snapshot 并持久化。

核心：execution identity = turn_id（不是 session_id）。一个 Session 可以有多个 Turn，
每个 Agent Task Turn 各自拥有自己的 snapshot，新 Turn 绝不覆盖旧 Turn。

引擎只负责 emit 事件（含 session_id）；本模块在 Web Runtime 层维护
session_id -> 当前 Turn 的映射，收到事件后更新对应 Turn 的 snapshot，
在 Turn 边界（engine:end / engine:awaiting_input）或 cancel 时落库收尾。
"""

from typing import Any, Callable, Dict, Optional

from .eventbus import event_bus
from .session import SessionManager, resolve_session_db_path
from .snapshot import RunSnapshotRecorder

_TURN_EVENTS = (
    "engine:start", "agent:thinking", "agent:switch", "tool:call", "tool:result",
    "engine:text", "engine:end", "budget:exceeded", "engine:error", "todo:updated",
    "tool:stream-start", "tool:stream-end", "engine:awaiting_input", "engine:user_input",
    "engine:evidence",
)

_TURN_BOUNDARY_EVENTS = {"engine:end", "engine:awaiting_input"}


def _snapshot_kind(snapshot: Dict[str, Any]) -> str:
    timeline = snapshot.get("timeline") or []
    has_task_signals = bool(
        (snapshot.get("tasks") or [])
        or (snapshot.get("resources") or [])
        or (snapshot.get("evidence") or [])
        or any(item.get("kind") == "handoff" for item in timeline)
    )
    return "agent_task" if has_task_signals else "direct_response"


def _assistant_answer(snapshot: Dict[str, Any]) -> Optional[str]:
    return (
        snapshot.get("final_report")
        or snapshot.get("partial_report")
        or snapshot.get("last_assistant_output")
    )


class TurnRecorder:
    def __init__(self, session_id: str, turn_id: str, on_finalize: Callable[[str, str], None]) -> None:
        self.session_id = session_id
        self.turn_id = turn_id
        self.on_finalize = on_finalize
        self.snapshot = RunSnapshotRecorder(session_id, run_id=turn_id)
        self._finalized = False
        self._subscriptions = []
        for event_name in _TURN_EVENTS:
            self._subscriptions.append(self._subscribe(event_name))

    def _subscribe(self, event_name: str):
        def handler(data: Dict[str, Any]) -> None:
            if self._finalized or data.get("session_id") != self.session_id:
                return
            self.snapshot.apply(event_name, data)
            if event_name in _TURN_BOUNDARY_EVENTS:
                self.finalize()
        event_bus.on(event_name, handler)
        return event_name, handler

    def _unsubscribe(self) -> None:
        for event_name, handler in self._subscriptions:
            event_bus.off(event_name, handler)
        self._subscriptions = []

    def _persist(self) -> None:
        snapshot = self.snapshot.to_dict()
        manager = SessionManager(resolve_session_db_path())
        try:
            manager.update_turn(
                self.turn_id,
                assistant_answer=_assistant_answer(snapshot),
                execution_snapshot=snapshot,
                status=snapshot["status"],
                kind=_snapshot_kind(snapshot),
            )
        finally:
            manager.close()

    def finalize(self) -> None:
        if self._finalized:
            return
        self._finalized = True
        self._unsubscribe()
        self._persist()
        self.on_finalize(self.session_id, self.turn_id)

    def finalize_as(self, reason: str) -> None:
        """引擎外终止（cancel/crash 兜底）：用 engine:end 事件收尾后再落库。"""
        if self._finalized:
            return
        self.snapshot.apply("engine:end", {"session_id": self.session_id, "reason": reason, "total_steps": self.snapshot.total_steps})
        self.finalize()


_active_turns: Dict[str, TurnRecorder] = {}


def _on_turn_finalized(session_id: str, turn_id: str) -> None:
    recorder = _active_turns.get(session_id)
    if recorder is not None and recorder.turn_id == turn_id:
        _active_turns.pop(session_id, None)


def start_turn(session_id: str, turn_id: str) -> None:
    """开始一次新 Turn：收尾旧的 active turn（若有），并订阅事件流。"""
    existing = _active_turns.pop(session_id, None)
    if existing is not None and not existing._finalized:
        existing.finalize()
    _active_turns[session_id] = TurnRecorder(session_id, turn_id, on_finalize=_on_turn_finalized)


def finalize_active_turn(session_id: str, reason: str = "cancelled") -> None:
    """引擎外终止当前 active turn（用户点停止等）。"""
    recorder = _active_turns.pop(session_id, None)
    if recorder is not None:
        recorder.finalize_as(reason)


def active_turn_id(session_id: str) -> Optional[str]:
    """返回当前 session 正在执行的 turn_id（用于给 SSE 事件标注 turn_id）。"""
    recorder = _active_turns.get(session_id)
    return recorder.turn_id if recorder is not None else None
