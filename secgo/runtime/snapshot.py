"""Run snapshot recorder：把实时执行过程中的可展示状态累积为可持久化的 RunSnapshot。

这是「历史 = 执行终态」的数据来源：实时 SSE 事件与历史 API 最终共享同一份
RunSnapshot，前端据此用同一套 Renderer 渲染 ExecutionBlock / RightPanel。

约定：
- 只记录允许展示给用户的信息（Agent 可读输出、工具调用、结果摘要、进度、证据、
  状态），绝不持久化隐藏 Chain-of-Thought 或内部系统 prompt。
- 时间戳统一为毫秒 epoch（与前端 Date 语义一致）。
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

# 明确属于「可复核事实」的工具：这些工具的结果天然是证据（web 检索 / DNS / 端口）。
# execute_bash / skill_list / skill_read / write_to_workspace / handoff 等一律不算证据。
EVIDENCE_TOOLS = {"web_search", "dns_lookup", "port_scan"}

_EVIDENCE_TITLE_BY_TOOL = {
    "web_search": "网页搜索结果",
    "dns_lookup": "DNS 查询结果",
    "port_scan": "端口扫描结果",
}

_EVIDENCE_TYPE_BY_TOOL = {
    "web_search": "finding",
    "dns_lookup": "network",
    "port_scan": "network",
}

_SNAPSHOT_DETAIL_CHARS = 2000
_SNAPSHOT_SUMMARY_CHARS = 400


def _bounded(value: Any, limit: int) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "…[已截断]"


def is_evidence_tool(tool_name: str) -> bool:
    return tool_name in EVIDENCE_TOOLS or tool_name.startswith("mcp_")


def classify_tool_evidence(tool_name: str, result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """把单个工具结果转换为 EvidenceRecord（或 None）。

    只有明确属于证据语义的工具结果才会成为证据；普通 Tool Result 一律不进 Evidence。
    """
    if not is_evidence_tool(tool_name):
        return None
    output = result.get("output") if result.get("success") else result.get("error")
    if output in (None, "", "(no output)"):
        return None
    summary = _bounded(output, _SNAPSHOT_SUMMARY_CHARS)
    return {
        "id": f"evidence-{uuid.uuid4().hex[:12]}",
        "type": _EVIDENCE_TYPE_BY_TOOL.get(tool_name, "finding" if tool_name.startswith("mcp_") else "artifact"),
        "title": _EVIDENCE_TITLE_BY_TOOL.get(tool_name, f"{tool_name} 结果"),
        "summary": summary,
        "source": tool_name,
        "timestamp": int(time.time() * 1000),
        "metadata": {"tool": tool_name, "success": bool(result.get("success"))},
    }


def _is_readable_narrative(text: str) -> bool:
    """镜像前端 readableNarrative 的轻量过滤：跳过 JSON / 工具结果 / 系统提示 / 交接文本。"""
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.startswith("{") or stripped.startswith("[{"):
        return False
    if stripped.startswith("[工具结果") or stripped.startswith("[系统提示") or stripped.startswith("[Handoff"):
        return False
    return True


class RunSnapshotRecorder:
    """累积一次 run 的可展示状态；支持从既有 snapshot 续跑（会话续聊）。"""

    def __init__(self, session_id: str, run_id: Optional[str] = None) -> None:
        self.run_id = run_id or str(uuid.uuid4())
        self.session_id = session_id
        self.turn_id = 1
        self.status = "running"
        self.phase = "planning"
        self.reason = ""
        self.error: Optional[str] = None
        self.active_agent = "planner"
        self.started_at = int(time.time() * 1000)
        self.ended_at: Optional[int] = None
        self.current_activity = ""
        self.narrative_updates: List[Dict[str, Any]] = []
        self.key_progress: List[str] = []
        self.key_findings: List[str] = []
        self.tasks: List[Dict[str, Any]] = []
        self.timeline: List[Dict[str, Any]] = []
        self.evidence: List[Dict[str, Any]] = []
        self.resources: List[Dict[str, Any]] = []
        self.final_report: Optional[str] = None
        self.partial_report: Optional[str] = None
        self.last_assistant_output: Optional[str] = None
        self.total_steps = 0
        self._timeline_seq = 0

    # ── 内部辅助 ─────────────────────────────────────────

    def _add_timeline(self, kind: str, title: str, detail: Optional[str] = None,
                      status: Optional[str] = None, agent: Optional[str] = None) -> None:
        self._timeline_seq += 1
        item: Dict[str, Any] = {
            "id": f"t{self._timeline_seq}",
            "at": int(time.time() * 1000),
            "kind": kind,
            "title": title,
        }
        if detail:
            item["detail"] = _bounded(detail, _SNAPSHOT_DETAIL_CHARS)
        if status:
            item["status"] = status
        if agent:
            item["agent"] = agent
        self.timeline.append(item)

    def _add_narrative(self, text: str, agent: str) -> None:
        if not _is_readable_narrative(text):
            return
        value = _bounded(text, 360)
        if any(item.get("text") == value for item in self.narrative_updates):
            return
        self.narrative_updates.append({
            "id": f"narrative-{len(self.narrative_updates) + 1}-{int(time.time() * 1000)}",
            "text": value,
            "agent": agent,
            "timestamp": int(time.time() * 1000),
        })

    def _append_unique(self, target: List[str], value: str) -> None:
        if value and value not in target:
            target.append(value)

    def _finish_resource(self, name: str, result: str) -> bool:
        """把 running 资源标记为 completed；若与最近一条已完成记录同名同结果则判重返回 False。"""
        if self.resources:
            last = self.resources[-1]
            if last.get("name") == name and last.get("status") == "completed" and last.get("result") == result:
                return False
        for idx in range(len(self.resources) - 1, -1, -1):
            entry = self.resources[idx]
            if entry.get("name") == name and entry.get("status") == "running":
                self.resources[idx] = {**entry, "status": "completed", "result": result}
                return True
        self.resources.append({
            "name": name,
            "status": "completed",
            "result": result,
            "at": int(time.time() * 1000),
        })
        return True

    def _derive_progress(self, name: str, result: Any) -> None:
        text = _bounded(result, 4000)
        if name == "skill_list":
            self._append_unique(self.key_progress, "已匹配当前任务所需安全能力")
        if name == "skill_read":
            self._append_unique(self.key_progress, "已加载所选安全测试执行指引")
        if "asp.net" in text.lower():
            self._append_unique(self.key_findings, "已识别目标使用 ASP.NET MVC 技术栈")
        for path in ("/admin", "/login", "/api", "/swagger", "/actuator"):
            if path in text.lower():
                self._append_unique(self.key_findings, f"发现 {path} 等入口")
        if "robots.txt" in text.lower() or "server:" in text.lower() or "x-powered-by" in text.lower():
            self._append_unique(self.key_progress, "已获取 robots.txt、HTTP 响应头或页面技术特征")

    def _terminal_title(self) -> str:
        if self.status == "completed":
            return "研判完成"
        if self.status == "stopped":
            return "任务已停止"
        return "任务结束"

    def _build_partial_report(self, reason: Optional[str] = None) -> str:
        """失败/停止时的确定性阶段性报告：不依赖再次调用模型。"""
        lines = ["# 执行未完整完成", "", "本次安全任务因故提前终止。"]
        term_reason = reason or self.error
        if term_reason:
            lines += ["", "## 终止原因", "", str(term_reason)]
        if self.key_findings:
            lines += ["", "## 已确认发现", ""]
            lines += [f"- {finding}" for finding in self.key_findings[:20]]
        if self.key_progress:
            lines += ["", "## 已完成步骤", ""]
            lines += [f"- {progress}" for progress in self.key_progress[:20]]
        if self.evidence:
            lines += ["", "## 已收集证据", ""]
            lines += [
                f"- **{item.get('title') or item.get('source', '')}**：{_bounded(item.get('summary'), 200)}"
                for item in self.evidence[:20]
            ]
        lines += ["", "## 建议", "", "修复模型连接或补充输入后继续当前任务。"]
        return "\n".join(lines)

    # ── 事件入口（后端侧的 reducer 镜像）──────────────────

    def apply(self, event_type: str, data: Dict[str, Any]) -> None:
        if event_type == "engine:start":
            self.status = "running"
            self.phase = "planning"
            self.current_activity = "Planner 正在规划执行路径"
            self._add_timeline("status", "任务已创建", status="running")
        elif event_type == "agent:thinking":
            agent = data.get("agent_id") or self.active_agent
            self.active_agent = agent
            self.phase = "reporting" if agent == "builder" else ("planning" if agent == "planner" else "executing")
            self.current_activity = "Builder 正在生成最终报告" if agent == "builder" else f"{agent} 正在执行"
            self._add_timeline("agent", f"{agent} 正在执行", status="running", agent=agent)
        elif event_type == "agent:switch":
            to_agent = data.get("to_agent_id") or self.active_agent
            from_agent = data.get("from_agent_id") or "agent"
            self.active_agent = to_agent
            self.phase = "reporting" if to_agent == "builder" else "executing"
            self.current_activity = f"{from_agent} 已移交 {to_agent}"
            self._append_unique(
                self.key_progress,
                f"已将{data.get('reason') or '当前阶段任务'}相关工作移交 {to_agent}",
            )
            self._add_timeline("handoff", f"{from_agent} → {to_agent}", detail=data.get("reason"), agent=to_agent)
        elif event_type in ("tool:call", "tool:stream-start"):
            name = data.get("tool_name") or "未知工具"
            self.phase = "executing"
            self.current_activity = f"{self.active_agent} 正在调用 {name}"
            self.resources.append({
                "name": name,
                "args": data.get("args"),
                "status": "running",
                "result": None,
                "at": int(time.time() * 1000),
            })
            self._add_timeline("tool", f"调用 {name}", status="running", agent=data.get("agent_id") or self.active_agent)
        elif event_type in ("tool:result", "tool:stream-end"):
            name = data.get("tool_name") or "未知工具"
            result_text = _bounded(data.get("result"), _SNAPSHOT_DETAIL_CHARS)
            self.phase = "executing"
            self.current_activity = f"{name} 已完成"
            if not self._finish_resource(name, result_text):
                return  # tool:stream-end 与 tool:result 同源，去重
            self._add_timeline(
                "tool", f"{name} 已完成",
                detail=_bounded(data.get("result"), 200),
                status="completed",
                agent=data.get("agent_id") or self.active_agent,
            )
            self._derive_progress(name, data.get("result"))
        elif event_type == "engine:evidence":
            evidence = data.get("evidence")
            if isinstance(evidence, dict):
                self.evidence.append(evidence)
        elif event_type == "engine:text":
            text = (data.get("text") or "").strip()
            agent = data.get("agent_id") or self.active_agent
            if not text:
                return
            self.last_assistant_output = text
            if agent == "builder":
                self.final_report = text
            else:
                self._add_narrative(text, agent)
        elif event_type == "todo:updated":
            self.tasks = list(data.get("todo_list") or [])
        elif event_type == "engine:awaiting_input":
            self.status = "awaiting_user"
            self.phase = "awaiting_user"
            self._add_timeline("status", "等待补充输入", detail=_bounded(data.get("message"), 500))
        elif event_type == "engine:user_input":
            self.status = "running"
            self.phase = "executing" if (self.tasks or self.resources) else "planning"
        elif event_type == "budget:exceeded":
            self.error = f"预算超限：{data.get('usage', 0)} / {data.get('limit', 0)} tokens"
            self._add_timeline("error", "预算超限", detail=self.error, status="error")
        elif event_type == "engine:error":
            self.error = data.get("error") or "引擎执行失败"
            self.phase = "error"
            self._add_timeline("error", "执行错误", detail=self.error, status="error")
        elif event_type == "engine:end":
            reason = data.get("reason") or "completed"
            self.reason = reason
            self.ended_at = int(time.time() * 1000)
            self.total_steps = int(data.get("total_steps", 0))
            if reason == "cancelled":
                self.status = "stopped"
                self.phase = "stopped"
                self.partial_report = self._build_partial_report("用户主动停止了本次执行。")
            elif reason == "completed":
                self.status = "completed"
                self.phase = "completed"
                if not self.final_report:
                    self.final_report = self.last_assistant_output or data.get("summary") or None
            else:
                self.status = "error"
                self.phase = "error"
                self.error = self.error or data.get("error") or reason
                self.partial_report = self._build_partial_report()
            self._add_timeline(
                "status", self._terminal_title(), detail=reason,
                status="completed" if self.status == "completed" else "error",
            )

    # ── 导出 ─────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "status": self.status,
            "phase": self.phase,
            "reason": self.reason,
            "error": self.error,
            "active_agent": self.active_agent,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "current_activity": self.current_activity,
            "narrative_updates": self.narrative_updates,
            "key_progress": self.key_progress,
            "key_findings": self.key_findings,
            "tasks": self.tasks,
            "timeline": self.timeline,
            "evidence": self.evidence,
            "resources": self.resources,
            "final_report": self.final_report,
            "partial_report": self.partial_report,
            "last_assistant_output": self.last_assistant_output,
            "tool_count": len(self.resources),
            "evidence_count": len(self.evidence),
            "total_steps": self.total_steps,
        }
