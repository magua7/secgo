"""Run snapshot recorder：把实时执行过程中的可展示状态累积为可持久化的 RunSnapshot。

这是「历史 = 执行终态」的数据来源：实时 SSE 事件与历史 API 最终共享同一份
RunSnapshot，前端据此用同一套 Renderer 渲染 ExecutionBlock / RightPanel。

约定：
- 只记录允许展示给用户的信息（Agent 可读输出、工具调用、结果摘要、进度、证据、
  状态），绝不持久化隐藏 Chain-of-Thought 或内部系统 prompt。
- 时间戳统一为毫秒 epoch（与前端 Date 语义一致）。
"""

from __future__ import annotations

import re
import time
import uuid
from typing import Any, Dict, List, Optional

# ── Evidence 来源资格（第一层之外的准入名单）────────────────────
# - EVIDENCE_TOOLS：结果天然是「对目标的直接探测事实」的工具（DNS / 端口），
#   成功 + 真实输出即可成为证据（confirmed 事实类）。
# - CANDIDATE_EVIDENCE_TOOLS（含 web_search）/ mcp_ 前缀：Evidence 候选来源。
#   候选 ≠ 自动成立：只有输出命中高价值安全信号（Flag、认证绕过、漏洞验证成功、
#   CVE、exploit/advisory 情报、敏感信息泄露等）才进入关键证据；普通输出只留在执行轨迹。
#   web_search 尤其如此：右栏是「关键证据」，普通网页搜索内容 ≠ 关键证据。
EVIDENCE_TOOLS = {"dns_lookup", "port_scan"}
CANDIDATE_EVIDENCE_TOOLS = {"execute_bash", "execute_workspace_script", "web_search"}

_EVIDENCE_TITLE_BY_TOOL = {
    "dns_lookup": "DNS 查询结果",
    "port_scan": "端口扫描结果",
}

_EVIDENCE_TYPE_BY_TOOL = {
    "dns_lookup": "network",
    "port_scan": "network",
}

# trusted 工具的置信度：端口/DNS 是对目标的直接探测事实
_EVIDENCE_CONFIDENCE_BY_TOOL = {
    "dns_lookup": "confirmed",
    "port_scan": "confirmed",
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
    """来源资格：trusted 工具或候选工具（含 mcp_ 前缀）才可能产出证据。"""
    return tool_name in EVIDENCE_TOOLS or _is_candidate_evidence_tool(tool_name)


def _is_candidate_evidence_tool(tool_name: str) -> bool:
    return tool_name in CANDIDATE_EVIDENCE_TOOLS or tool_name.startswith("mcp_")


_NO_RESULT_MARKERS = (
    "no search results found", "no search results", "no results found", "no results",
    "no result", "no data", "0 results", "no matches", "no records", "nothing found",
    "no vulnerabilities found", "no open ports", "not found", "no output", "no search result",
)


def _is_no_result_output(text: str) -> bool:
    """识别「无有效结果」输出：空结果不应成为关键证据。"""
    low = text.strip().lower().rstrip(".。！!")
    if not low:
        return True
    if low in _NO_RESULT_MARKERS:
        return True
    if len(low) <= 120 and any(
        low.startswith(m) for m in ("no search", "no results", "no result", "no data",
                                    "no matches", "0 results", "nothing found", "not found")
    ):
        return True
    return False


# ── 第二层：结构化 / 规则判断 ─────────────────────────────────
# 关键词只是第一层快速识别，真正的判定是「工具成功 + 有真实输出 + 命中高价值安全信号」。
# 命中的是「结果内容」而非「用了什么工具」：execute_bash 与 mcp_* 的输出与
# web_search 走同一套信号规则，不因工具名而自动放行。

_FLAG_RE = re.compile(r"\b(?:ctf|flag)\{[^{}\s]{2,120}\}", re.IGNORECASE)

_EVIDENCE_SIGNAL_DEFS = (
    {
        "key": "exploit_success",
        "title": "漏洞利用验证成功",
        "type": "finding",
        "confidence": "confirmed",
        "patterns": (
            re.compile(
                r"(?:sql\s*injection|xss|ssrf|rce|command\s*injection|path\s*traversal|"
                r"lfi|rfi|ssti|xxe|insecure\s+deserialization|arbitrary\s+file\s+(?:read|upload))\b"
                r"[^;\n]{0,120}\b(?:confirmed|verified|successful|succeeded|works?)\b",
                re.IGNORECASE,
            ),
            re.compile(r"\bsuccessfully\s+(?:exploited|executed|triggered|achieved)\b", re.IGNORECASE),
            re.compile(
                r"\b(?:authentication|auth|login|authorization)\s+bypass\s+(?:was\s+)?"
                r"(?:successful|succeeded|confirmed|verified)",
                re.IGNORECASE,
            ),
        ),
    },
    {
        "key": "auth_privilege",
        "title": "认证绕过/权限提升验证成功",
        "type": "finding",
        "confidence": "confirmed",
        "patterns": (
            re.compile(r"\blogged[\s_-]?in\s+as\s+(an?\s+)?admin(?:istrator)?\b", re.IGNORECASE),
            re.compile(r"\byou\s+are\s+(now\s+)?(an?\s+)?admin(?:istrator)?\b", re.IGNORECASE),
            re.compile(r"\bwelcome\b.{0,20}\badministrator\b", re.IGNORECASE),
            re.compile(r"\bprivilege\s+escalation\s+(?:was\s+)?(?:successful|succeeded|achieved)", re.IGNORECASE),
            re.compile(r"\brole[=:]\s*admin\b[^;\n]{0,60}\b(?:ok|success|welcome|accepted|granted)\b", re.IGNORECASE),
        ),
    },
    {
        "key": "cve_intel",
        "title": "发现相关 CVE 漏洞情报",
        "type": "finding",
        "confidence": "probable",
        "patterns": (re.compile(r"\bCVE-\d{4}-\d{4,7}\b"),),
    },
    {
        "key": "open_ports",
        # nmap 风格 “80/tcp open” 与 port_scan 输出 “2 open port(s): 80, 443”
        "title": "发现开放端口/暴露服务",
        "type": "network",
        "confidence": "confirmed",
        "patterns": (
            re.compile(r"\b\d{1,5}/tcp\s+open"),
            re.compile(r"\b[1-9]\d*\s+open\s+ports?\(", re.IGNORECASE),
        ),
    },
    {
        "key": "service_banner",
        "title": "获取服务版本/Banner 信息",
        "type": "network",
        "confidence": "confirmed",
        "patterns": (
            re.compile(r"(?m)^[ \t]*(?:Server|X-Powered-By|Banner)[ \t]*[:|]"),
            re.compile(
                r"\b(?:nginx|apache|microsoft-?iis|openssh|mysql|postgresql|redis|tomcat|jenkins)"
                r"[/ ]v?\d+\.\d+",
                re.IGNORECASE,
            ),
        ),
    },
    {
        "key": "sensitive_leak",
        "title": "敏感信息泄露证据",
        "type": "file",
        "confidence": "probable",
        "patterns": (
            re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # JWT
            re.compile(r"\broot:[x*!]?:0:0:"),  # /etc/passwd 内容读取
            re.compile(
                r"\b(?:password|passwd|api[_-]?key|secret|access[_-]?token)\s*[=:]\s*\S{6,}",
                re.IGNORECASE,
            ),
        ),
    },
    {
        # exploit / advisory / PoC 类明确攻击指标（常见于 web_search 情报结果）
        "key": "exploit_intel",
        "title": "发现漏洞利用/安全公告情报",
        "type": "finding",
        "confidence": "probable",
        "patterns": (
            re.compile(r"\bEDB-\d{4,7}\b", re.IGNORECASE),
            re.compile(r"\bpublic(?:ly)?\s+(?:available\s+)?exploit\b", re.IGNORECASE),
            re.compile(r"\bexploit\s+(?:code|chain|payload)\s+(?:is\s+)?available\b", re.IGNORECASE),
            re.compile(r"\b(?:security|vulnerability)\s+advisory\b", re.IGNORECASE),
            re.compile(r"\bproof[\s-]*of[\s-]*concept\b", re.IGNORECASE),
        ),
    },
)

# web_search 的信号白名单：搜索结果只有命中「安全情报类」信号才进入关键证据。
# open_ports / service_banner 是对目标的直接探测信号——它们出现在搜索结果里
# 只是普通技术文档内容（如 nginx 版本介绍），不构成关键证据。
_WEB_SEARCH_SIGNAL_KEYS = {"exploit_success", "auth_privilege", "cve_intel", "sensitive_leak", "exploit_intel"}

_MAX_EVIDENCE_PER_RESULT = 4


def _unique_flags(text: str) -> List[str]:
    flags: List[str] = []
    seen: set[str] = set()
    for match in _FLAG_RE.finditer(text):
        value = match.group(0)
        low = value.lower()
        if low not in seen:
            seen.add(low)
            flags.append(value)
    return flags


def _matched_line(text: str, match: "re.Match[str]") -> str:
    """提取命中所在的一行作为证据摘要，退化为命中片段本身。"""
    start = text.rfind("\n", 0, match.start()) + 1
    end = text.find("\n", match.end())
    if end == -1:
        end = len(text)
    line = text[start:end].strip()
    return _bounded(line, _SNAPSHOT_SUMMARY_CHARS) or _bounded(match.group(0), _SNAPSHOT_SUMMARY_CHARS)


def _make_evidence_record(
    tool_name: str,
    *,
    title: str,
    type_: str,
    confidence: str,
    summary: str,
    signal: str,
    dedupe_key: str,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {
        "tool": tool_name,
        "success": True,
        "signal": signal,
        "confidence": confidence,
        "dedupe_key": dedupe_key,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    return {
        "id": f"evidence-{uuid.uuid4().hex[:12]}",
        "type": type_,
        "title": title,
        "summary": summary,
        "source": tool_name,
        "confidence": confidence,
        "timestamp": int(time.time() * 1000),
        "metadata": metadata,
    }


def build_evidence_records(tool_name: str, result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """把单个工具结果转换为 0..N 条 EvidenceRecord（分层 Gate）。

    判定链：执行成功？ → 有真实有效输出？ → 是否命中高价值安全发现？ → 是否重复？
    - 第一层（确定性 Gate）：success=False / 空输出 / no-result / timeout 等一律拒绝；
    - 第二层（结构化规则）：按结果内容匹配 Flag / 漏洞验证 / 认证绕过 / CVE /
      exploit-advisory 情报 / 敏感泄露等信号，候选工具（execute_bash、web_search、
      mcp_* 等）只有命中信号才成为证据——普通 ls、普通网页介绍不会进入关键证据；
    - trusted 工具（dns_lookup / port_scan）保持旧行为：成功且有真实输出即为
      对目标的直接探测事实；若同时命中更强信号则用具体信号卡片。
    """
    if not result.get("success"):
        return []
    output = result.get("output")
    if output in (None, "", "(no output)"):
        return []
    text = output if isinstance(output, str) else str(output)
    if _is_no_result_output(text):
        return []

    trusted = tool_name in EVIDENCE_TOOLS
    if not trusted and not _is_candidate_evidence_tool(tool_name):
        return []

    records: List[Dict[str, Any]] = []

    # 高价值强证据：Flag（跨工具通用，逐个唯一 Flag 一条）
    for flag_value in _unique_flags(text)[:2]:
        records.append(_make_evidence_record(
            tool_name,
            title="Flag 获取成功",
            type_="finding",
            confidence="confirmed",
            summary=f"{tool_name} 结果中获取到 Flag：{flag_value}",
            signal="flag",
            dedupe_key=f"flag:{flag_value.lower()}",
            extra_metadata={"flag": flag_value},
        ))

    # web_search 只允许安全情报类信号（其余搜索内容留在执行轨迹 / Research 输出）
    allowed_signal_keys = _WEB_SEARCH_SIGNAL_KEYS if tool_name == "web_search" else None
    used_signal_keys: set[str] = set()
    for sig in _EVIDENCE_SIGNAL_DEFS:
        if sig["key"] in used_signal_keys or len(records) >= _MAX_EVIDENCE_PER_RESULT:
            continue
        if allowed_signal_keys is not None and sig["key"] not in allowed_signal_keys:
            continue
        for pattern in sig["patterns"]:
            match = pattern.search(text)
            if match:
                used_signal_keys.add(sig["key"])
                line = _matched_line(text, match)
                records.append(_make_evidence_record(
                    tool_name,
                    title=sig["title"],
                    type_=sig["type"],
                    confidence=sig["confidence"],
                    summary=line,
                    signal=sig["key"],
                    dedupe_key=f"{sig['key']}:{_normalize_ws(line).lower()[:160]}",
                ))
                break

    # trusted 工具兜底：未命中任何具体信号时保留旧版「事实类证据」行为
    if not records and trusted:
        records.append({
            "id": f"evidence-{uuid.uuid4().hex[:12]}",
            "type": _EVIDENCE_TYPE_BY_TOOL.get(tool_name, "artifact"),
            "title": _EVIDENCE_TITLE_BY_TOOL.get(tool_name, f"{tool_name} 结果"),
            "summary": _bounded(text, _SNAPSHOT_SUMMARY_CHARS),
            "source": tool_name,
            "confidence": _EVIDENCE_CONFIDENCE_BY_TOOL.get(tool_name, "informational"),
            "timestamp": int(time.time() * 1000),
            "metadata": {
                "tool": tool_name,
                "success": True,
                "signal": "generic_fact",
                "dedupe_key": f"fact:{tool_name}:{_normalize_ws(text).lower()[:160]}",
            },
        })
    return records[:_MAX_EVIDENCE_PER_RESULT]


def classify_tool_evidence(tool_name: str, result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """兼容入口：返回该工具结果的首条 Evidence（或 None）。

    分层 Gate 见 build_evidence_records：只有「执行成功 + 存在真实有效结果 +
    不是 error/no-result/timeout」且命中高价值信号（dns/port 等直接探测类
    trusted 工具可为通用事实类）才会成为证据。工具类型只是来源资格，不是成立条件。
    """
    records = build_evidence_records(tool_name, result)
    return records[0] if records else None


def evidence_dedupe_key(record: Dict[str, Any]) -> str:
    """证据去重键：优先使用生成时注入的关键值键（Flag/CVE/端口等），否则退化为 source+归一化摘要。"""
    meta = record.get("metadata") or {}
    key = meta.get("dedupe_key") if isinstance(meta, dict) else None
    if isinstance(key, str) and key.strip():
        return key.strip()
    source = str(record.get("source") or "")
    summary = _normalize_ws(str(record.get("summary") or "")).lower()[:160]
    return f"raw:{source}:{summary}"


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


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
    """累积一次 run 的可展示状态（事件 → 持久化 RunSnapshot）。"""

    def __init__(self, session_id: str, run_id: Optional[str] = None, turn_id: Optional[str] = None) -> None:
        self.run_id = run_id or str(uuid.uuid4())
        self.session_id = session_id
        # turn_id 必须是 conversation_turns.id（真实 Turn UUID string），绝不写死为 1 / sequence / index。
        # run≈turn 时 run_id 即 turn_id；独立 runId 场景仍可区分。
        self.turn_id = turn_id or self.run_id
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
        self.decisions: List[Dict[str, Any]] = []
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
            self.phase = "planning" if agent == "planner" else "executing"
            self.current_activity = f"{agent} 正在执行"
            self._add_timeline("agent", f"{agent} 正在执行", status="running", agent=agent)
        elif event_type == "agent:switch":
            to_agent = data.get("to_agent_id") or self.active_agent
            from_agent = data.get("from_agent_id") or "agent"
            self.active_agent = to_agent
            self.phase = "executing"
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
                # 去重：关键值键（Flag/CVE/端口等）相同即视为重复；退化兜底同源+同摘要
                key = evidence_dedupe_key(evidence)
                duplicate = any(
                    evidence_dedupe_key(item) == key
                    or (
                        item.get("source") == evidence.get("source")
                        and item.get("summary") == evidence.get("summary")
                    )
                    for item in self.evidence
                )
                if not duplicate:
                    self.evidence.append(evidence)
        elif event_type == "decision:reason":
            decision = data.get("decision")
            if isinstance(decision, dict):
                trigger_detail = _bounded(decision.get("trigger_detail"), 200)
                reason = _bounded(decision.get("reason"), 200)
                self.decisions.append(decision)
                # 决策同时在执行轨迹留下简版节点
                self._add_timeline(
                    "finding",
                    "◆ 策略调整",
                    detail=f"{trigger_detail} → {reason}".strip(" →"),
                    status="completed",
                )
        elif event_type == "engine:text":
            text = (data.get("text") or "").strip()
            agent = data.get("agent_id") or self.active_agent
            if not text:
                return
            self.last_assistant_output = text
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
            "decisions": self.decisions[-20:],
            "tool_count": len(self.resources),
            "evidence_count": len(self.evidence),
            "total_steps": self.total_steps,
        }